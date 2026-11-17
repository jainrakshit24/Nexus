"""Serena adapter — LSP-grade symbol references, as a third impact source.

The installed Serena build (oraios/serena, probed 2026-11-16) does not expose
`find_symbol`/`find_referencing_symbols` as individual MCP tools. Every context
collapses them into one `serena_repl` tool that runs Python against a facade
object `s`, gated by a session id handed out by `initial_instructions`.

So this adapter drives that REPL, which is the only surface that exists. It is
opt-in for a reason: a cold start costs a few seconds, and the REPL contract is
Serena's internal shape, not a published API. Every failure path returns None
with a reason rather than a guess, and impact analysis degrades to graph + text.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from .mcpclient import MCPClient, MCPError
from .symbols import iter_text_files

SESSION_RE = re.compile(r"session id is [`'\"]([A-Za-z0-9_-]+)[`'\"]")

DEFAULT_COMMAND = ["uvx", "--from", "git+https://github.com/oraios/serena",
                   "serena", "start-mcp-server", "--context", "ide-assistant"]


def available() -> bool:
    return shutil.which("uvx") is not None or shutil.which("serena") is not None


class Serena:
    """One Serena session, held open for the life of the `with` block."""

    def __init__(self, project: Path, timeout: float = 120.0, command: list[str] | None = None):
        self.project = str(Path(project).resolve())
        base = command or ([ "serena", "start-mcp-server", "--context", "ide-assistant"]
                           if shutil.which("serena") and not shutil.which("uvx") else DEFAULT_COMMAND)
        self.command = [*base, "--project", self.project]
        self.client = MCPClient(self.command, cwd=self.project, timeout=timeout)
        self.session: str | None = None

    def __enter__(self) -> Serena:
        self.client.start()
        instructions = MCPClient.text_of(self.client.call("initial_instructions", {}))
        m = SESSION_RE.search(instructions)
        if not m:
            self.client.stop()
            raise MCPError("Serena did not hand out a session id; its REPL contract has changed")
        self.session = m.group(1)
        return self

    def __exit__(self, *exc) -> None:
        self.client.stop()

    def repl(self, code: str) -> str:
        if not self.session:
            raise MCPError("not started")
        return MCPClient.text_of(self.client.call("serena_repl", {"session": self.session, "code": code}))

    def referencing_symbols(self, symbol: str, relative_path: str) -> dict | None:
        """{file: {kind: [refs]}} from the language server, or None if unusable."""
        code = f"s.lsp.find_referencing_symbols({symbol!r}, {relative_path!r})"
        try:
            raw = self.repl(code)
        except MCPError:
            return None
        raw = raw.strip()
        if not raw or raw.startswith(("NameError", "Traceback", "Error", "AttributeError")):
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

# --------------------------------------------------------------------------
# Per-project cache
#
# A Serena query costs ~4.7s, almost all of it language-server cold start, and
# a second run costs the same because nothing was kept. References can change
# from an edit anywhere in the repo, not just in the target file, so the cache
# is keyed on a signature of every text file's mtime and size: if that is
# unchanged, no edit happened and the previous answer is still correct. The
# walk costs milliseconds against seconds, and a changed repo drops the whole
# cache rather than serving one entry that might be stale.
# --------------------------------------------------------------------------

CACHE_FILE = "serena-cache.json"


def repo_signature(project: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(iter_text_files(Path(project))):
        try:
            st = f.stat()
        except OSError:
            continue
        h.update(f"{f}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    return h.hexdigest()[:16]


def _cache_path(project: Path) -> Path:
    return Path(project) / ".nexus" / CACHE_FILE


def load_cache(project: Path, signature: str) -> dict:
    """Entries from a repository in exactly this state, or nothing."""
    try:
        blob = json.loads(_cache_path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if blob.get("signature") != signature:
        return {}        # the repo moved; every answer in here is suspect
    entries = blob.get("entries")
    return entries if isinstance(entries, dict) else {}


def save_cache(project: Path, signature: str, entries: dict) -> None:
    path = _cache_path(project)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"signature": signature, "entries": entries}),
                        encoding="utf-8")
    except OSError:
        pass             # a cache that cannot be written is not an error


def referencing_files(project: Path, symbols: list[str], relative_path: str,
                      timeout: float = 120.0,
                      use_cache: bool = True) -> tuple[dict[str, list[str]], str | None]:
    """Files referencing any of these symbols. Returns (hits, error_reason).

    `error_reason` is a note, not a failure: a caller that cannot reach Serena
    still gets the graph and text evidence, and is told why this half is missing.
    """
    sig = repo_signature(project) if use_cache else ""
    cached = load_cache(project, sig) if use_cache else {}
    key = f"{relative_path}::{','.join(sorted(symbols))}"
    if key in cached:
        return {f: list(syms) for f, syms in cached[key].items()}, None

    if not available():
        return {}, "serena not installed (needs `uvx` or `serena` on PATH)"
    hits: dict[str, list[str]] = {}
    try:
        with Serena(project, timeout=timeout) as s:
            for sym in symbols:
                data = s.referencing_symbols(sym, relative_path)
                if not data:
                    continue
                for file in data:
                    hits.setdefault(file, []).append(sym)
    except (MCPError, OSError) as e:
        return hits, f"serena unavailable: {str(e)[:160]}"

    if use_cache:
        cached[key] = hits
        save_cache(project, sig, cached)
    return hits, None
