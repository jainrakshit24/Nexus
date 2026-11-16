# NEXUS — Engineering Intelligence & Memory System

Local-first engineering companion: understands a codebase, remembers its evolution,
protects its integrity, and carries that context across Claude Code, Codex and Cursor.

**Status:** Phase 1 complete (31 tests green). See `docs/PHASE1.md`. Phase 2 next.

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
cd <your repo>
nexus init .                 # discover the project, create .nexus/
nexus remember "..." --confidence verified --source file.py:12
nexus recall auth token      # keyword + confidence-weighted retrieval
nexus show <name>            # record + its supersede history
nexus status
```
