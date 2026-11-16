# Phase 2 — Understanding & Impact · COMPLETE (2026-11-16)

Joins the memory engine to the code. This is the join ADR 0001 called NEXUS's
actual product: graphify knows the code, memory knows the decisions, and until
now nothing connected them.

## What shipped

| Module | Does |
|---|---|
| `nexus/graph.py` | graphify adapter: locate `graphify-out/`, load the node-link graph, reverse-edge lookup to any depth, staleness from the manifest. |
| `nexus/symbols.py` | The non-graph half: exported-name extraction, word-boundary reference search, Python AST outlines. |
| `nexus/impact.py` | Unions graph + text + language server + tests into one answer, each dependent carrying which sources found it, and scores blast radius. |
| `nexus/tokens.py` | Token counting and the three-number accounting, with a JSONL log. |
| `nexus/context.py` | Priority-ordered context packing under a hard token budget. |
| `nexus/mcpclient.py` | Minimal MCP stdio client (JSON-RPC 2.0). Also the transport Phase 4's NEXUS server needs. |
| `nexus/serena.py` | Serena adapter over that client, opt-in. |

New commands: `nexus impact · context · tokens · graph`.

## Acceptance criteria — results

| # | Criterion | Result |
|---|---|---|
| 1 | impact finds every dependent a manual grep finds, **plus at least one grep missed** | **PASS** — 7 vs grep's 4. The three extras (`nexus/context.py`, `tests/conftest.py`, `tests/test_cli.py`) are transitive dependents that never contain the string `record`. grep's one extra was a false positive inside a comment. |
| 2 | context pack never exceeds `--budget`, verified by the real tokenizer, over 20 varied tasks | **PASS** — 20 tasks × 3 budgets (200/800/4000), every pack within budget. |
| 3 | editing a file surfaces a stale warning **without rebuilding** the graph | **PASS** — demonstrated live mid-build: editing `cli.py` and adding four modules was reported as `STALE: 1 changed, 4 never indexed` from the manifest alone. |
| 4 | `nexus tokens` prints three numbers separately; "estimated" on `saved` only | **PASS** — asserted in `test_tokens.py`; host usage prints `unavailable` with a reason rather than a guess. |
| 5 | recall@5 measured on a 50-question benchmark, recorded whatever it is | **PASS (number is marginal)** — **0.70**, exactly on the upgrade trigger. Full numbers in `BENCHMARK.md`. |

**83 tests, 2.7 s.** All Phase 1 tests still pass.

## Three findings that changed the design

1. **graphify has no build command.** The `graphify` binary exposes `path`, `explain`,
   `merge-graphs` and exports — the build pipeline is the `/graphify` *skill*, driven by
   an agent. The blueprint said "graphify adapter: run/update"; that capability does not
   exist to call. NEXUS therefore **reads** graphs and reports staleness, and
   `nexus graph` prints the exact command a human or agent must run. Stated rather than
   faked, per the brief's rule about not inventing capabilities.

2. **Serena no longer exposes symbol tools over MCP.** Every context in the installed
   build (`ide-assistant`, `agent`, `desktop-app`) collapses to 2–3 tools, with
   `find_symbol` / `find_referencing_symbols` reachable only by running Python against a
   facade object `s` inside `serena_repl`, gated by a session id handed out in
   `initial_instructions`. `serena tools list` still advertises ~28 tools; they are
   internal now. The adapter drives that REPL because it is the only surface that exists,
   returns clean JSON, and is opt-in because it costs ~4.7 s per call.

3. **A one-line tokenizer change beat an architecture change.** Before reaching for
   embeddings, switching FTS5 to `porter unicode61` lifted recall@5 from 0.64 to 0.70.
   The remaining misses are genuine vocabulary gaps, which is the honest case *for*
   embeddings — now recommended as the first Phase 3 item rather than assumed in Phase 2.

## Defects found and fixed during the phase

1. **Weak text evidence inflated blast radius.** `to_markdown` exists in two modules;
   a word match cannot tell a reference from a collision. Text-only hits are now
   reported but excluded from the radius whenever the graph answered — and counted,
   with the reason saying so, when there is no graph.
2. **A stale index was silently wrong.** Changing the FTS tokenizer does not change an
   existing `index.db`, so old stores would keep ranking by the old rules forever. The
   schema now carries a version in `PRAGMA user_version`, and a mismatch rebuilds from
   Markdown on the next command.
3. **Depth-1 impact could not beat grep.** In a Python package where everything is
   explicitly imported, one hop is what grep already sees. Reverse traversal to arbitrary
   depth is what makes the graph worth having — and it is what passed AC1.

## Known limits (carried into Phase 3)

- **Recall@5 is 0.70, on the trigger.** Hybrid retrieval with local embeddings is the
  recommended first Phase 3 task; the benchmark exists to prove or disprove the gain.
- Staleness is mtime-based, so touch-without-edit reads as stale. Safe direction, still wrong.
- `nexus impact` takes one target at a time; a multi-file change is several calls.
- The Serena REPL contract is Serena's internals, not a published API, and may break on
  upgrade. It degrades to graph + text with a visible note when it does.
- Nothing yet *enforces* the workflow gear that impact recommends. That is Phase 3.
