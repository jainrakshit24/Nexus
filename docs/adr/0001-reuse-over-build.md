# ADR 0001 — Reuse the installed stack; build only the join

**Date:** 2026-11-16 · **Status:** accepted

## Context
The NEXUS brief asks for a knowledge graph, code intelligence, agent
orchestration, memory, a dashboard and cross-platform adapters. A survey of this
machine found working implementations of four of those six already installed:
graphify (graph), Serena (code intelligence, installed today), Claude Code
subagents + superpowers/gsd/ecc (orchestration), claude-hud (dashboard).

## Decision
NEXUS builds **only** what no installed component provides:
1. durable, confidence-scored project memory;
2. the join between that memory and the code graph;
3. impact-driven context packing with honest token accounting;
4. pre/post-edit engineering gates;
5. one MCP surface + thin per-host adapters.

Everything else is invoked as an external process. Nothing is vendored.

## Alternatives considered
- **Build a graph engine** — rejected: graphify is installed, incremental, and already exports to Neo4j/GraphML.
- **Adopt Letta as the runtime** — rejected: it owns the agent loop, which makes NEXUS platform-dependent, contradicting the core requirement.
- **Adopt Mem0 / claude-mem as the memory store** — rejected: each would be a *second* memory store alongside the convention already in use, and claude-mem is Claude-Code-only. Their capture-on-hook design is adopted; their storage is not.

## Consequences
- **Good:** small codebase, no vendored licenses, each engine upgradeable independently.
- **Bad:** NEXUS is only as good as graphify's extraction and Serena's LSP coverage. Mitigated by the union-of-sources impact strategy (§4 of the blueprint).
- **Obligation:** every external engine sits behind exactly one adapter module with a fixture test, so a breaking upstream change is a one-file fix.
