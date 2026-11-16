# Cross-platform compatibility

Every row says **tested** or **untested**. A row is `tested` only if the
integration was actually run on this machine and the result observed. Nothing
here is inferred from documentation.

Last verified 2026-11-16.

## Hosts

| Host | Transport | Config NEXUS writes | Status | Evidence |
|---|---|---|---|---|
| **Claude Code** | MCP stdio | `.mcp.json`, `.claude/NEXUS.md`, `.claude/settings.json` | **tested** | Registered with `claude mcp add` and `claude mcp get nexus` reported `✔ Connected`. Tools list returned all five. |
| **Any MCP client** (generic) | MCP stdio | — | **tested** | NEXUS's own `MCPClient` drives the server over a real subprocess in `tests/test_server.py`; 19 tests including two independently-configured launches returning identical answers. |
| **Codex** | MCP stdio | `AGENTS.md`, block for `~/.codex/config.toml` | **untested** | The `codex` binary is not installed here. Config is generated and its TOML shape asserted in tests, but no live handshake was observed. |
| **Cursor** | MCP stdio | `.cursor/mcp.json`, `.cursor/rules/nexus.mdc` | **untested** | No `cursor` binary on this machine. JSON validity is asserted; no live handshake. |
| **VS Code / Copilot** | MCP stdio | `.vscode/mcp.json`, `.github/copilot-instructions.md` | **untested** | VS Code is installed but the MCP integration was not exercised. |

## Capabilities by host

| Capability | Claude Code | Codex | Cursor | VS Code |
|---|---|---|---|---|
| The five MCP tools | tested | untested | untested | untested |
| Project instruction file | tested (`.claude/NEXUS.md`) | generated (`AGENTS.md`) | generated (`.mdc` rule) | generated (copilot-instructions) |
| SessionStart context injection | generated, **handler tested** | not supported by the host's config model | not supported | not supported |
| Test-run capture hook | generated, **handler tested** | not supported | not supported | not supported |
| Status line (compact dashboard) | available via `statusLine` | not applicable | not applicable | not applicable |

"Handler tested" means `nexus hook session-start` / `post-tool` were exercised
directly with representative payloads (`tests/test_adapters.py`); the host
firing them was not observed.

## What is genuinely portable

The `.nexus/` directory. It is Markdown plus a rebuildable SQLite index, so it
moves with the repository and between hosts without conversion. Two
differently-configured server launches reading the same directory return
byte-identical answers — asserted, not claimed
(`test_two_differently_configured_hosts_get_identical_answers`).

## Known gaps

- Hooks are a Claude Code feature. Codex and Cursor have no equivalent
  lifecycle-event mechanism in their configuration model, so automatic capture
  is Claude-Code-only. The MCP tools work identically everywhere.
- `~/.codex/config.toml` and other global host configs are **printed, never
  written**. Overwriting a user's global agent configuration is not NEXUS's
  call to make.
- The protocol version is echoed back to the client rather than negotiated from
  a supported set, because this server implements only the subset every dated
  MCP revision shares. If a future revision changes `tools/call`, this will need
  a real negotiation table.
