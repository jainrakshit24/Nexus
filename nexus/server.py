"""NEXUS as an MCP server: one surface, every host.

Claude Code, Codex and Cursor all speak MCP over stdio, so this module is
the whole integration story. Each host adapter is configuration, not code.

stdout carries JSON-RPC and nothing else. Anything else written there
corrupts the protocol, so every diagnostic goes to stderr.
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any
from collections.abc import Callable

from . import context as context_mod
from . import gate as gate_mod
from . import scrub, tokens as tokens_mod
from .impact import analyze
from .record import CONFIDENCE, TIERS, Record
from .store import NotInitialized, Store, find_root

# A client that asks for a version the server does not name simply disconnects,
# so echo what the client asked for: this server implements only the subset of
# MCP that every dated revision shares (initialize, tools/list, tools/call).
PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "nexus"


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def _error(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}], "isError": True}


# --------------------------------------------------------------------------
# tools
# --------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "nexus_recall",
        "description": "Retrieve what this project already knows about a topic. "
                       "Ranked by keyword match and weighted by confidence, so a "
                       "verified fact outranks an assumption. Call this before "
                       "reading files: it is far cheaper and often sufficient.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "what you want to know"},
                "type": {"type": "string", "enum": list(TIERS)},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
    },
    {
        "name": "nexus_remember",
        "description": "Store one verified fact about this project. Use it after you "
                       "have proved something — a test went green, a schema changed, a "
                       "decision was made. confidence=verified requires a source "
                       "(file:line, commit, or test run). Credentials are refused.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "name": {"type": "string"},
                "type": {"type": "string", "enum": list(TIERS), "default": "project"},
                "confidence": {"type": "string", "enum": list(CONFIDENCE), "default": "observed"},
                "source": {"type": "string", "description": "file:line, commit sha, or test run"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "nexus_impact",
        "description": "What else breaks if this file or symbol changes. Unions the code "
                       "graph, text references and tests; depth 2 finds transitive "
                       "dependents that never mention the target. Call this before editing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "file path or symbol name"},
                "depth": {"type": "integer", "default": 2},
            },
            "required": ["target"],
        },
    },
    {
        "name": "nexus_context",
        "description": "Assemble everything needed for a task — relevant memory, impact, "
                       "file outlines — inside a token budget. Returns the pack plus its "
                       "measured cost against the cost of reading the files whole.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "budget": {"type": "integer", "default": 4000},
            },
            "required": ["task"],
        },
    },
    {
        "name": "nexus_gate",
        "description": "stage=pre: a written plan before editing — dependents, roles, "
                       "risks, and whether an ADR is required. stage=post: the verdict "
                       "after editing — diff, unintended changes, credentials, and tests "
                       "actually executed with their output captured.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": ["pre", "post"]},
                "targets": {"type": "array", "items": {"type": "string"},
                            "description": "files you are about to change (stage=pre)"},
                "run_tests": {"type": "boolean", "default": True,
                              "description": "stage=post: actually execute the test suite"},
            },
            "required": ["stage"],
        },
    },
]


def tool_recall(root: Path, args: dict) -> dict:
    results = Store(root).recall(args["query"], type_=args.get("type"),
                                 limit=int(args.get("limit", 8)))
    if not results:
        return _text("No memory matches that. Nothing is known about it yet.")
    out = []
    for r in results:
        body = Path(r["path"]).read_text(encoding="utf-8").split("---", 2)[-1].strip()
        src = f" — source: {r['source']}" if r["source"] else ""
        out.append(f"### {r['name']}  [{r['confidence']}]{src}\n{body}")
    return _text("\n\n".join(out))


def tool_remember(root: Path, args: dict) -> dict:
    store = Store(root)
    try:
        rec = Record(
            name=args.get("name") or " ".join(args["text"].split()[:8]),
            type=args.get("type", "project"), body=args["text"],
            confidence=args.get("confidence", "observed"), source=args.get("source", ""),
        )
        action, rec, warnings = store.write(rec)
    except scrub.SecretFound as e:
        return _error(f"Refused: {e}. Store a pointer to the secret, never the secret.")
    except ValueError as e:
        return _error(str(e))
    note = "".join(f"\nwarning: {w.pattern}" for w in warnings)
    return _text(f"{action}: {rec.name} [{rec.type}/{rec.confidence}] {rec.id}{note}")


def tool_impact(root: Path, args: dict) -> dict:
    imp = analyze(root, args["target"], depth=int(args.get("depth", 2)))
    lines = [f"{imp.target}: blast radius {imp.blast_radius}, workflow {imp.gear}",
             f"reason: {imp.reason()}",
             f"graph: {imp.staleness.summary() if imp.staleness else 'unavailable'}"]
    lines += [f"note: {n}" for n in imp.notes]
    lines.append("")
    for d in imp.dependents:
        hop = f"{d.hops} hop" if d.hops else "text"
        lines.append(f"[{d.strength}] {d.file} ({hop}) via {', '.join(sorted(d.sources))}")
    return _text("\n".join(lines) or "no dependents found")


def tool_context(root: Path, args: dict) -> dict:
    pack = context_mod.build(root, args["task"], budget=int(args.get("budget", 4000)))
    acc = pack.accounting()
    tokens_mod.record(root, acc)
    return _text(pack.render() + "\n---\n" + "\n".join(acc.lines()))


def tool_gate(root: Path, args: dict) -> dict:
    stage = args.get("stage")
    if stage == "pre":
        targets = args.get("targets") or []
        if not targets:
            return _error("stage=pre needs `targets`: the files you are about to change")
        plan = gate_mod.pre_edit(root, targets)
        gate_mod.save_plan(root, plan)
        body = plan.render()
        return _error(body + "\nBLOCKED: write the ADR before editing.") if plan.blocked else _text(body)
    if stage == "post":
        verdict = gate_mod.post_edit(root, run=bool(args.get("run_tests", True)))
        body = verdict.render()
        return _error(body) if verdict.status in ("BLOCKED", "FAIL") else _text(body)
    return _error("stage must be 'pre' or 'post'")


HANDLERS: dict[str, Callable[[Path, dict], dict]] = {
    "nexus_recall": tool_recall,
    "nexus_remember": tool_remember,
    "nexus_impact": tool_impact,
    "nexus_context": tool_context,
    "nexus_gate": tool_gate,
}


# --------------------------------------------------------------------------
# protocol
# --------------------------------------------------------------------------

class Server:
    def __init__(self, root: Path | None = None):
        self._root = Path(root).resolve() if root else None

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = find_root()
        return self._root

    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method")
        mid = msg.get("id")
        if mid is None:
            return None  # a notification: never answered

        try:
            if method == "initialize":
                asked = (msg.get("params") or {}).get("protocolVersion")
                result: Any = {
                    "protocolVersion": asked or PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": _version()},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = msg.get("params") or {}
                name = params.get("name")
                handler = HANDLERS.get(name)
                if handler is None:
                    return _rpc_error(mid, -32602, f"unknown tool: {name}")
                try:
                    result = handler(self.root, params.get("arguments") or {})
                except NotInitialized as e:
                    result = _error(f"{e}")
                except Exception:
                    print(traceback.format_exc(), file=sys.stderr)
                    result = _error(f"{name} failed: {traceback.format_exc(limit=1).strip()}")
            else:
                return _rpc_error(mid, -32601, f"method not found: {method}")
        except Exception as e:   # protocol-level failure, still answer
            print(traceback.format_exc(), file=sys.stderr)
            return _rpc_error(mid, -32603, str(e))

        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            response = self.handle(msg)
            if response is not None:
                stdout.write(json.dumps(response) + "\n")
                stdout.flush()
        return 0


def _rpc_error(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _version() -> str:
    from . import __version__
    return __version__


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    if "--root" in argv:
        root = Path(argv[argv.index("--root") + 1])
    return Server(root).serve()


if __name__ == "__main__":
    raise SystemExit(main())
