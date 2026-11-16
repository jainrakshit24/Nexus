"""Host adapters: configuration, not code.

Every supported host speaks MCP over stdio, so each adapter's job is to
write the few lines that point that host at `nexus.server`, plus the
instruction file that tells the agent when to call it.

Adapters are pure generators — they return (path, content) pairs and write
only when asked — so what they produce can be tested without touching a
real configuration directory.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

GUIDANCE = """\
## NEXUS

This project has a NEXUS memory and code-intelligence server. Prefer it over
re-deriving what the project already knows.

- **Before answering a question about this codebase**, call `nexus_recall`.
  It is far cheaper than reading files and often sufficient.
- **Before editing any file**, call `nexus_impact` on it. Depth 2 finds
  dependents that never mention the file by name.
- **For a non-trivial change**, call `nexus_gate` with `stage: "pre"` first.
  It returns the dependents that must keep working, which specialists the
  change earns, and whether an ADR is required. If it reports BLOCKED, write
  the ADR before editing.
- **After editing**, call `nexus_gate` with `stage: "post"`. It runs the real
  test suite and captures the output. A pass is never reported without one.
- **When you have proved something** — a test went green, a schema changed, a
  decision was made — call `nexus_remember` with `confidence: "verified"` and
  a source. Do not record guesses as facts, and never store a credential.
- `nexus_context` assembles memory, impact and file outlines inside a token
  budget when you are starting a task from cold.
"""


@dataclass
class Artifact:
    path: str          # relative to the project root, or ~-prefixed for user scope
    content: str
    note: str = ""


def server_command(root: Path, python: str | None = None) -> dict:
    """How a host should launch the NEXUS server."""
    return {
        "command": python or sys.executable,
        "args": ["-m", "nexus.server", "--root", str(Path(root).resolve())],
        "env": {"PYTHONPATH": str(Path(__file__).resolve().parents[1])},
    }


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------

def claude_code(root: Path, python: str | None = None, hooks: bool = True) -> list[Artifact]:
    root = Path(root).resolve()
    nexus_bin = shutil.which("nexus") or "nexus"
    out = [
        Artifact(".mcp.json",
                 json.dumps({"mcpServers": {"nexus": server_command(root, python)}}, indent=2) + "\n",
                 "project-scoped MCP server; Claude Code picks this up automatically"),
        Artifact(".claude/NEXUS.md", GUIDANCE,
                 "reference this from CLAUDE.md, or paste it in"),
    ]
    if hooks:
        settings = {
            "hooks": {
                "SessionStart": [{
                    "hooks": [{"type": "command",
                               "command": f"{nexus_bin} hook session-start",
                               "timeout": 15}]
                }],
                "PostToolUse": [{
                    "matcher": "Bash",
                    "hooks": [{"type": "command",
                               "command": f"{nexus_bin} hook post-tool",
                               "timeout": 15}]
                }],
            }
        }
        out.append(Artifact(
            ".claude/settings.json", json.dumps(settings, indent=2) + "\n",
            "SessionStart injects the project profile; PostToolUse records a test run "
            "as an episodic memory — only when a test command actually ran"))
    return out


# --------------------------------------------------------------------------
# Codex
# --------------------------------------------------------------------------

def codex(root: Path, python: str | None = None) -> list[Artifact]:
    root = Path(root).resolve()
    cmd = server_command(root, python)
    args = ", ".join(f'"{a}"' for a in cmd["args"])
    toml = (
        "# Append to ~/.codex/config.toml\n"
        "[mcp_servers.nexus]\n"
        f'command = "{cmd["command"]}"\n'
        f"args = [{args}]\n"
        f'env = {{ PYTHONPATH = "{cmd["env"]["PYTHONPATH"]}" }}\n'
    )
    return [
        Artifact("AGENTS.md", GUIDANCE, "Codex reads AGENTS.md from the project root"),
        Artifact("~/.codex/config.toml", toml, "append this block; do not overwrite the file"),
    ]


# --------------------------------------------------------------------------
# Cursor / VS Code
# --------------------------------------------------------------------------

def cursor(root: Path, python: str | None = None) -> list[Artifact]:
    root = Path(root).resolve()
    rule = "---\ndescription: NEXUS memory and code intelligence\nalwaysApply: true\n---\n\n" + GUIDANCE
    return [
        Artifact(".cursor/mcp.json",
                 json.dumps({"mcpServers": {"nexus": server_command(root, python)}}, indent=2) + "\n",
                 "project-scoped MCP server for Cursor"),
        Artifact(".cursor/rules/nexus.mdc", rule, "always-applied project rule"),
    ]


def vscode(root: Path, python: str | None = None) -> list[Artifact]:
    root = Path(root).resolve()
    cmd = server_command(root, python)
    return [
        Artifact(".vscode/mcp.json",
                 json.dumps({"servers": {"nexus": {"type": "stdio", **cmd}}}, indent=2) + "\n",
                 "VS Code MCP config (Copilot agent mode)"),
        Artifact(".github/copilot-instructions.md", GUIDANCE,
                 "Copilot reads this from the repository"),
    ]


HOSTS = {"claude-code": claude_code, "codex": codex, "cursor": cursor, "vscode": vscode}


def generate(host: str, root: Path, python: str | None = None) -> list[Artifact]:
    if host not in HOSTS:
        raise ValueError(f"unknown host {host!r}; choose from {sorted(HOSTS)}")
    return HOSTS[host](Path(root), python)


def write(root: Path, artifacts: list[Artifact], force: bool = False) -> list[tuple[str, str]]:
    """Writes project-relative artifacts. Never touches ~ paths — those are printed
    for the user to apply, because overwriting a host's global config is not ours to do."""
    results = []
    for a in artifacts:
        if a.path.startswith("~"):
            results.append((a.path, "skipped (global config — apply this by hand)"))
            continue
        target = Path(root) / a.path
        if target.exists() and not force:
            results.append((a.path, "exists — not overwritten (use --force)"))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(a.content, encoding="utf-8")
        results.append((a.path, "written"))
    return results
