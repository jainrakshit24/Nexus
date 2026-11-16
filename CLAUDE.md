# NEXUS — project instructions

**This is a standalone project.** It has no relationship to any other repository,
client or body of work on this machine. Do not import context, terminology,
examples or history from elsewhere, and do not cite other local projects in its
code, docs or commits. A `CLAUDE.md` in a parent directory does not apply here —
this file does.

## What NEXUS is

A local-first engineering memory and code-intelligence system. It gives an agent
durable project memory, joins that memory to a code knowledge graph, answers
"what breaks if this changes", and packs task context under a token budget.

Read `docs/BLUEPRINT.md` for the architecture and `docs/PHASES.md` for the plan.
Current state and measurements: `docs/PHASE1.md`, `docs/PHASE2.md`, `docs/BENCHMARK.md`.

## Hard rules

- **NEXUS never runs an LLM loop.** The host agent does. Any change to that
  boundary needs a new ADR in `docs/adr/`.
- **Never invent a capability.** If a dependency cannot do something, say so in
  the docs and offer the real alternative. Two deliverables were already scoped
  down this way (see `docs/PHASE2.md`, "Three findings").
- **Never report a measurement that was not taken.** `saved` is always labelled
  *estimated*; `actual` and `baseline` are measured; missing host data prints
  `unavailable`, never a guess.
- **No credentials, no personal data, no absolute home paths** in code, docs,
  tests or commit messages. The repo must read as if written by anyone, for anyone.
- **Markdown is the source of truth; SQLite is a rebuildable cache.** Any change
  that breaks that must be rejected.

## Working style

- Reuse before building. Four of NEXUS's six capabilities are external tools
  invoked behind a single adapter module each (ADR 0001). Keep it that way.
- Every adapter gets a fixture-backed test so an upstream break is a one-file fix.
- New non-trivial logic ships with a test. `python3 -m pytest tests -q` must be green.
- Benchmarks live in `bench/`; record the number you got, not the number you wanted.

## Commands

```bash
python3 -m pytest tests -q      # test suite
python3 bench/run_recall.py     # retrieval benchmark
nexus status | graph | impact <file> | context "<task>" --budget N | tokens
```

The graph comes from `/graphify .` run in an agent. NEXUS reads graphs; it never
builds them.
