# NEXUS — Research: what already exists

Verified on this machine 2026-11-16 unless marked *(web, unverified)*.

## Already installed here — do not rebuild

| Capability | What's installed | Evidence |
|---|---|---|
| Knowledge graph | **graphify** skill (`~/.claude/skills/graphify`) — tree-sitter extraction, community detection, incremental `--update`, `--mcp` stdio server, Neo4j/FalkorDB/GraphML export, `query`/`path`/`explain` | SKILL.md read; an existing `graphify-out/` was found in a local project |
| Graph runtime deps | `networkx 3.4.2`, `tree_sitter`, `sqlite3 3.37.2`, Python 3.10.12, Node 22, uv 0.11 | import checks passed |
| Code intelligence | **Serena** MCP — LSP-backed `find_symbol`, `find_referencing_symbols`, `replace_symbol_body`, 40+ languages | installed + `Status: ✔ Connected` this session |
| Orchestration primitives | Claude Code subagents (90+ agent types), `superpowers` 7.0.2, `gsd` suite, `ecc` 2.2.3 (reviewers for python/go/rust/security/db/arch) | `installed_plugins.json` |
| Dashboard surface | **claude-hud** 0.14.2 (pane beside chat), plus a local-dashboard pattern already proven in another project here | installed plugins |
| Memory convention | `~/.claude/projects/<project>/memory/` — single-fact Markdown files + a `MEMORY.md` index, frontmatter typed `user/feedback/project/reference` | directory listing |
| Cross-agent memory spec | `ecc:unified-memory` — portable `ecc.memory.v1` Markdown vault shared across Claude/Codex/Cursor/Hermes | SKILL.md (needs `npm i -g ecc-universal` runtime, not installed) |

## Evaluated, not adopted

| Project | What it gives | License *(web)* | Verdict |
|---|---|---|---|
| **Mem0** | extract-and-retrieve memory layer beside an agent | Apache-2.0 *(one source says "open core"; graph features reportedly Pro-gated)* | **No for v1.** Adds a service + vector store to replicate what Markdown + SQLite FTS5 + graphify already do locally. Revisit only if measured recall fails. |
| **Letta (MemGPT)** | full stateful-agent *runtime*, self-editing core memory + archival | Apache-2.0 *(web)* | **No.** It wants to own the agent loop. Claude Code / Codex already own it. Taking Letta means NEXUS becomes platform-dependent — the exact thing the brief forbids. |
| **claude-mem** | Claude Code plugin, hooks session lifecycle, SQLite, auto-injects prior context | OSS plugin *(web)* | **No, but steal the shape.** It is Claude-Code-only and would be a *second* competing memory store next to the existing `memory/` convention. Copy its hook-driven capture idea; keep one store. |
| **LangGraph** | graph-based agent orchestration | MIT *(web)* | **No.** NEXUS does not run its own LLM loop; the host agent does. |
| **Neo4j / FalkorDB** | graph database | — | **Optional export only.** graphify already emits Cypher. Don't make a DB a hard dependency. |
| **Tree-sitter / NetworkX** | parsing / graph algorithms | MIT / BSD-3 | **Yes — already in use via graphify.** Direct use only where graphify doesn't reach. |
| **MCP** | tool transport, cross-client | open spec | **Yes.** NEXUS exposes itself as one MCP server → one integration, every client. |
| **Agent Skills spec + AGENTS.md** | portable instruction format | open | **Yes.** Primary portability vehicle. |

## Attribution / license posture

- Nothing is vendored. Serena and graphify are invoked as external processes (MCP / CLI) — no source copying, no license entanglement.
- If any code is ever copied: record it in `docs/adr/` with the upstream license text before the commit.
- NEXUS's own code: MIT, to stay compatible with everything above.

## Honest gaps found

1. No local system today links *memory* to *graph*. graphify knows the code; `memory/` knows the decisions; nothing joins them. **That join is NEXUS's actual product.**
2. No impact analysis before edit anywhere in the stack.
3. No measured token accounting — claude-hud shows usage, nothing computes *savings*.
4. Staleness is undetected: graphify has `--update` but nothing *blocks* work on a graph that has drifted from HEAD.
