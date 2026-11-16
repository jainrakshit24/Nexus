"""Hook handlers for agent hosts.

Two rules govern everything here:

1. **A broken hook must never break the session.** Every handler swallows its
   own failures and exits 0 with no output.
2. **Capture verified outcomes, not conversation.** The post-tool hook records
   a memory only when a test command actually ran and reported an exit code.
   Nothing else about a session becomes a "fact".
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .graph import load as load_graph
from .record import Record
from .store import NotInitialized, Store, find_root

TEST_COMMAND_HINT = re.compile(
    r"\b(pytest|npm (run )?test|yarn test|pnpm test|go test|cargo test|mvn test|"
    r"gradlew test|bundle exec (rspec|rake)|phpunit|jest|vitest|make test)\b")


def _root(explicit: str | None = None) -> Path | None:
    """A hint only counts if it really is a NEXUS project.

    Without this check a hook fired in an unrelated directory would create a
    `.nexus/` there, because opening the store creates it.
    """
    try:
        if explicit:
            p = Path(explicit).resolve()
            return p if (p / ".nexus").is_dir() else None
        return find_root()
    except (NotInitialized, OSError):
        return None


def session_start(payload: dict, root_hint: str | None = None) -> str:  # noqa: ARG001
    """A short orientation block. Deliberately small — it costs context."""
    root = _root(root_hint)
    if root is None:
        return ""
    lines: list[str] = []
    store = Store(root)
    try:
        stats = store.stats()
    except Exception:
        return ""

    overview = store.recall("project overview stack test command", type_="project", limit=1)
    if overview:
        body = Path(overview[0]["path"]).read_text(encoding="utf-8").split("---", 2)[-1].strip()
        lines.append(body.split("\n\nDiscovered by")[0].strip())

    lines.append(f"NEXUS memory: {stats['live']} live record(s), {stats['superseded']} superseded.")
    try:
        g = load_graph(root)
        s = g.staleness(root, extensions={".py", ".js", ".ts", ".go", ".rs"})
        lines.append(f"Knowledge graph: {len(g.nodes)} nodes — {s.summary()}")
    except Exception:
        lines.append("Knowledge graph: not built (run `/graphify .` to create one).")

    lines.append("Call nexus_recall before reading files, and nexus_impact before editing one.")
    return "\n".join(lines)


def post_tool(payload: dict, root_hint: str | None = None) -> str:
    """Record a test run as episodic memory. Silent for everything else."""
    if payload.get("tool_name") != "Bash":
        return ""
    command = ((payload.get("tool_input") or {}).get("command") or "").strip()
    if not command or not TEST_COMMAND_HINT.search(command):
        return ""

    root = _root(root_hint)
    if root is None:
        return ""

    response = payload.get("tool_response") or {}
    # Hosts differ on the field name; absence means we learned nothing.
    code = response.get("exit_code", response.get("exitCode", response.get("returncode")))
    if code is None:
        return ""

    output = str(response.get("stdout") or response.get("output") or "")
    tail = "\n".join(output.strip().splitlines()[-3:])
    verdict = "passed" if code == 0 else f"failed with exit {code}"

    try:
        store = Store(root)
        store.write(Record(
            name=f"test-run-{'pass' if code == 0 else 'fail'}",
            type="episodic",
            body=f"`{command}` {verdict}.\n\n{tail}".strip(),
            confidence="verified",
            source=f"observed test run, exit {code}",
            tags=["test-run"],
        ))
    except Exception:
        return ""
    return ""


def pre_commit(payload: dict, root_hint: str | None = None) -> int:  # noqa: ARG001
    """Block a commit whose gate verdict is FAIL or BLOCKED. Returns an exit code.

    Deliberately does **not** run the test suite by default: a pre-commit hook
    that takes minutes is a pre-commit hook everybody bypasses, and a bypassed
    gate protects nothing. Set NEXUS_GATE_TESTS=1 to include them.
    """
    import os
    from . import gate as gate_mod

    root = _root(root_hint)
    if root is None:
        return 0                       # not a NEXUS project: not our business

    run_tests = os.environ.get("NEXUS_GATE_TESTS") == "1"
    try:
        verdict = gate_mod.post_edit(root, run=run_tests, staged=True)
    except Exception as e:
        print(f"nexus: gate could not run ({e}); allowing the commit", file=sys.stderr)
        return 0                       # a broken gate must not wedge the repo

    if verdict.status in ("BLOCKED", "FAIL"):
        print(verdict.render(), file=sys.stderr)
        print("\nnexus: commit blocked. Fix the above, or bypass deliberately with "
              "NEXUS_SKIP_GATE=1 before the commit command.", file=sys.stderr)
        return 1

    if verdict.breaking:
        print(f"nexus: {len(verdict.breaking)} breaking API change(s) in this commit — "
              f"allowed, but review them:", file=sys.stderr)
        for b in verdict.breaking:
            print(f"  {b['symbol']}: {b['change']}", file=sys.stderr)
    if not verdict.tests.ran:
        print("nexus: tests were not run by this hook (set NEXUS_GATE_TESTS=1 to include them)",
              file=sys.stderr)
    return 0


HANDLERS = {"session-start": session_start, "post-tool": post_tool}
GATE_HOOKS = {"pre-commit": pre_commit}


def run(name: str, stream=None, root_hint: str | None = None) -> int:
    """Entry point.

    Context hooks always exit 0 — a hook that fails must not stop the agent.
    Gate hooks are the exception: blocking is the entire point of one.
    """
    if name in GATE_HOOKS:
        return GATE_HOOKS[name]({}, root_hint)

    handler = HANDLERS.get(name)
    if handler is None:
        return 0
    try:
        raw = (stream or sys.stdin).read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    try:
        text = handler(payload, root_hint)
    except Exception:
        return 0
    if text:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart" if name == "session-start" else "PostToolUse",
                "additionalContext": text,
            }
        }))
    return 0
