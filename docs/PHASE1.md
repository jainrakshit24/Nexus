# Phase 1 — Foundation & Memory · COMPLETE (2026-11-16)

## What shipped

| Module | Does |
|---|---|
| `nexus/scrub.py` | Secret + PII scan before any disk write. 14 blocking patterns, 4 warning patterns, adapted from ECC `opensource-sanitizer`. |
| `nexus/record.py` | The record: Markdown + YAML frontmatter, ULID-shaped ids, confidence tiers, content hashing. |
| `nexus/store.py` | 5-tier Markdown store + SQLite FTS5 index, write/supersede/recall/reindex/forget/chain. |
| `nexus/discover.py` | Project profile: stack, test command, entrypoints, census, git state. |
| `nexus/cli.py` | `init · remember · recall · show · forget · reindex · status` |

CLI entry: `~/.local/bin/nexus` (dev shim onto the source tree — no reinstall on edit).

## Acceptance criteria — results

| # | Criterion | Result |
|---|---|---|
| 1 | `nexus init` on a real repo yields a test command that **actually runs** | **PASS** — on a real local Python repo whose tests sit two directories below the root, it detected `pytest <nested>/tests`; running that command gave `138 passed, 35 subtests passed in 73.88s`. Required adding nested-test discovery and file-type stack inference: the repo has no root marker file. |
| 2 | `recall` < 300 ms on 500 records | **PASS** — measured p50 **0.8 ms**, max 1.0 ms. 284 KB index. |
| 3 | AWS key / JWT / DB URL writes are blocked, pattern named | **PASS** — CLI exits `3`, names the pattern, writes nothing. 5 payload types tested; excerpts never print the full secret. |
| 4 | Delete the index, `reindex`, get identical recall | **PASS** — verified in tests and on the real repo, byte-identical ids and scores. |
| 5 | Conflicts supersede; history readable, excluded from recall | **PASS** — old file moves to `.nexus/superseded/<name>.<id>.md`, `show` prints the chain, `recall --all` includes it. |
| 6 | pytest green, ≥1 test per rule | **PASS** — **31 tests**, 1.9 s. |

## Two defects found and fixed during the phase

1. **Unstable recall order.** Equal-scoring records came back in insertion order, so AC4 failed after a rebuild. Fixed with an id tiebreaker — recall is now reproducible.
2. **Root-only project detection.** Missed tests nested in a monorepo. Fixed with a depth-3 scan plus stack inference from the file census, labelled `inferred` so it is never mistaken for a read marker file.

## Design notes worth keeping

- **Markdown is the truth; SQLite is a cache.** Proven by AC4, not asserted.
- **`verified` requires a `--source`.** Enforced in the constructor, so no code path can mint an unsourced fact.
- **Secrets hard-fail, PII warns.** Project memory has legitimate reasons to mention an internal host; it has none to hold a credential.
- **Confidence weights retrieval** (verified 1.0 / observed 0.85 / assumed 0.7) so an assumption cannot outrank a verified fact on equal text.
- **Relevance is relative.** Raw bm25 on a small corpus is ~1e-6 and meaningless alone; the CLI shows 0-100 against the best hit in the set.

## Known limits (carried into Phase 2)

- `graph_refs` is stored and indexed but nothing populates it yet — that is the Phase 2 join.
- No staleness detection: a record pointing at `src/auth.py:40` is not re-checked when that file changes.
- Recall is keyword-only. The recall@5 benchmark that decides whether embeddings are needed is a Phase 2 deliverable.
- The dev shim hardcodes an absolute path to the source tree. Fine for one machine; packaging is Phase 4.
