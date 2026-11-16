# Phase 4 — Surfaces & Proof · COMPLETE (2026-11-16)

Phases 1–3 built the engine. Phase 4 makes it reachable from any agent host,
and proves the claims with numbers rather than prose.

## What shipped

| Module | Does |
|---|---|
| `nexus/server.py` | NEXUS as an MCP stdio server: `nexus_recall · remember · impact · context · gate`. stdout carries JSON-RPC and nothing else. |
| `nexus/adapters.py` | Host configuration as pure generators — Claude Code, Codex, Cursor, VS Code. Returns (path, content); writes only when asked, and never to a global config. |
| `nexus/hooks.py` | SessionStart orientation and test-run capture. A broken hook always exits 0; only verified outcomes become memory. |
| `nexus/dashboard.py` | Localhost page (127.0.0.1 only) and a one-line compact status. Structurally unreachable from the agent-facing server. |

New commands: `nexus serve · dashboard · install · hook`.

## Acceptance criteria — results

| # | Criterion | Result |
|---|---|---|
| 1 | The same `.nexus/` gives the same answers in two hosts — **demonstrated, not asserted in prose** | **PASS** — `test_two_differently_configured_hosts_get_identical_answers` launches two real server subprocesses with different working directories and environments, runs three queries through each, and asserts the answers are byte-identical. A fact written through one host is recalled through the other. |
| 2 | Dashboard shows memory, graph staleness, active role and the three token numbers — and adds **0 tokens** to the agent's context | **PASS** — zero-token is enforced structurally, not promised: a test asserts `nexus/server.py` never mentions the dashboard, no tool schema references it, and no handler returns its content. The page reads the same files on disk that the tools write. |
| 3 | Compatibility matrix marks every row tested or untested; nothing claims untested support | **PASS** — `docs/COMPATIBILITY.md`. One host is `tested` (Claude Code, `✔ Connected`), three are `untested` with the reason stated: their binaries are not on this machine. |
| 4 | Cold start on a 10k-file repo, measured and recorded | **PASS** — 10,101 files: discovery 101 ms, MCP launch → initialize **44 ms**, first recall over MCP 2.7 ms, impact without a graph 318 ms. Full table in `BENCHMARK.md`. |
| 5 | Full suite green; earlier phases still pass | **PASS** — **178 tests, 5.0 s**. |

## The bug that only a real host could find

`claude mcp get nexus` reported **`✘ Failed to connect`** while NEXUS's own client
talked to the same server perfectly. The server was answering `initialize` with a
hardcoded `protocolVersion` of `2026-11-05` — a date that is not a real MCP
revision. A client that receives a version it does not recognise disconnects, so
the handshake completed and then the connection was dropped.

The server now echoes the version the client asked for, and defaults to
`2025-06-18` when none is given. This is honest for a server that implements only
the subset every dated revision shares — `initialize`, `tools/list`, `tools/call` —
and `docs/COMPATIBILITY.md` says so, along with when it will need real negotiation.

After the fix: `Status: ✔ Connected`.

Three regression tests cover it, including one asserting the default is a real
dated revision rather than an invented one.

## Other defects found

1. **A hook could create `.nexus/` in an unrelated directory.** `hooks._root`
   trusted its path hint, and opening a store creates its directory. A hook
   fired outside a project would quietly litter. The hint now counts only if
   `.nexus/` is already there.

2. **The MCP registration I typed by hand failed where the generated config
   would have worked.** `claude mcp add` without `PYTHONPATH` cannot import an
   uninstalled package. `adapters.server_command()` has always included that
   env var — the adapter was right and the hand-written command was wrong,
   which is the argument for generating these files rather than documenting them.

## Design notes

- **One server, four adapters.** Each adapter is configuration only. Adding a
  fifth host is a function returning (path, content) pairs — no new protocol
  code, no new tools.
- **Global configs are printed, never written.** `~/.codex/config.toml` belongs
  to the user. NEXUS prints the block to append.
- **Capture records outcomes, not conversation.** The post-tool hook fires only
  on a command that looks like a test run *and* only when the host reported an
  exit code. Without an exit code nothing was learned, so nothing is stored.
- **Zero-token is structural.** Had the dashboard been merely "not usually
  called by the agent", it would eventually have been called. It is not
  importable from the server, and a test keeps it that way.

## Known limits

- **Local embeddings remain the open decision from Phase 2.** recall@5 is 0.70,
  exactly on the trigger. Four phases have now deferred it.
- Codex, Cursor and VS Code configs are generated but never handshaken here.
- Hooks are Claude-Code-only; the other hosts have no lifecycle-event model.
- The dashboard polls every 3 s and holds no history — it shows the present, not
  a trend.
- `nexus install` writes project files; it does not restart or notify a running host.
