# NEXUS — Engineering Intelligence & Memory System

Local-first engineering companion: understands a codebase, remembers its evolution,
protects its integrity, and carries that context across Claude Code, Codex and Cursor.

**Status:** five phases complete — **209 tests green**. See `docs/PHASE1.md` … `docs/PHASE5.md`, with measurements in `docs/BENCHMARK.md`, host support in `docs/COMPATIBILITY.md`, and decisions in `docs/adr/`.

- `docs/RESEARCH.md` — what already exists, licenses, what to reuse vs build
- `docs/BLUEPRINT.md` — architecture, memory lifecycle, storage, security, token strategy
- `docs/PHASES.md` — the 4-phase build plan with acceptance criteria
- `docs/adr/` — architecture decision records

## Guiding rule

NEXUS is mostly **wiring, not engine-building**. Graph, code intelligence,
orchestration primitives and the HUD already exist on this machine. NEXUS adds the
thin layer they are missing: durable project memory, impact-aware context packing,
engineering gates, and cross-platform portability.

## Quick start

```bash
pip install .                # or: pip install -e . --no-build-isolation

cd <your repo>
nexus init .                 # discover the project, create .nexus/
nexus remember "..." --confidence verified --source file.py:12
nexus recall auth token      # keyword + confidence-weighted retrieval
nexus show <name>            # record + its supersede history
nexus status
nexus consolidate            # fold old episodes into monthly summaries

nexus graph                  # graph size + staleness, no rebuild
nexus impact nexus/store.py --depth 2   # what breaks if this changes
nexus context "refactor X" --budget 4000
nexus tokens                 # actual / baseline / estimated saved

nexus plan src/billing.py    # pre-edit: dependents, roles, risks, ADR check
nexus verify                 # post-edit: diff, secrets, tests (really runs them)
nexus adr new "Title" --affects src/billing.py
nexus env --write            # .env.example from keys only, never values
nexus debt add "..." --where src/billing.py:40
```

## Use it from your agent

```bash
nexus install claude-code     # or codex / cursor / vscode / all
nexus install all --dry-run   # see what would be written first
```

That points the host at `nexus serve`, an MCP server exposing five tools:
`nexus_recall`, `nexus_remember`, `nexus_impact`, `nexus_context`, `nexus_gate`.
Host support, tested and untested, is listed in `docs/COMPATIBILITY.md`.

## Watch it

```bash
nexus dashboard               # localhost page, 127.0.0.1 only
nexus dashboard --compact     # one line, for a status bar
```

The dashboard reads `.nexus/` on disk. It is not reachable from the MCP server,
so it costs the agent zero context tokens — enforced by a test, not a promise.

Requires a graphify graph for the strongest impact evidence: run `/graphify .`
in your agent once, then `--update` when it goes stale. NEXUS reads graphs; it
does not build them.
