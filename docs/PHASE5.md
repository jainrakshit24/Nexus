# Phase 5 — Retrieval & Memory Integrity · COMPLETE (2026-11-16)

Phases 1–4 shipped a system that stored facts well and found them only adequately,
and never re-checked a fact after the code beneath it moved. This phase closes both
gaps — and settles a decision that four phases had deferred.

## What shipped

| Area | Change |
|---|---|
| **The join** | `store.graph_neighbour_files()` + `records_anchored_to()`: retrieval now traverses the code graph as well as the keyword index. |
| **Automatic anchoring** | A record sourced at `src/auth.py:40` resolves its own `graph_refs` and `ref_files`. Nothing is invented when the path does not resolve. |
| **Memory staleness** | `verified_at` is finally read. A verified fact whose source file changed, or vanished, says so in `recall`, `status` and on the dashboard. |
| **Episodic consolidation** | `nexus consolidate` folds old episodes into one summary per month. Nothing is deleted; originals stay on disk and `recall --all` finds them. |
| **Packaging** | Real `pip install`. The shim with an absolute path baked in is gone. |

New command: `nexus consolidate`. `recall` gained `--via` markers and stale labels.

## Acceptance criteria — results

| # | Criterion | Result |
|---|---|---|
| 1 | A query sharing **no keywords** with its answer, linked only through the graph, is retrieved in the top 5 | **PASS** — `test_the_question_names_a_neighbour_and_the_answer_arrives_anyway`. Asking about `beta` returns the fact about `alpha`, tagged `via: graph`. A companion test runs the same query with `expand=False` and asserts it is **invisible**, so the graph is demonstrably doing the work. |
| 2 | `--source path:line` populates `graph_refs` automatically; unresolvable sources invent nothing | **PASS** — four tests, including `source: "commit a1b2c3d"` yielding an empty list and hand-supplied refs never being overwritten. |
| 3 | A verified record whose source changed is labelled stale in recall, status and dashboard; re-verifying clears it | **PASS** — eight tests. Observed and assumed facts are never labelled, because they never claimed currency. |
| 4 | recall@5 re-measured and recorded; the embeddings question closed by an ADR quoting the number | **PASS** — **0.70, unchanged**, because that benchmark's facts are anchored to nothing. A second benchmark measures what expansion actually adds: **0.00 → 1.00**. `ADR 0002` closes the decision. |
| 5 | Old episodes consolidate into a summary; originals readable, excluded from default recall; nothing deleted | **PASS** — eleven tests, including a dry run that changes nothing and a summary that is never folded into another summary. |
| 6 | `pip install .` in a clean virtualenv gives a working `nexus` with no reference to the dev tree; shim removed | **PASS** — installed into a fresh venv, ran `init · remember · recall · impact` against a scratch project; `grep` for the development path in its output returns **0**. The shim is replaced by a real console script. |
| 7 | Everything still green | **PASS** — **209 tests, 6.0 s**. |

## The decision this phase was really about

Four phases deferred local embeddings. `BLUEPRINT.md §5` had pre-registered the
rule before any measurement: *add them if recall@5 drops below 0.7.*

The number is **0.70**. It did not drop below. `ADR 0002` records the decision not
to add them, and says plainly what would reopen it. Moving the threshold after
seeing the number would have made writing it down beforehand pointless.

The more useful finding is that the paraphrase benchmark **cannot see** graph
expansion at all — its facts have no files behind them. The second benchmark shows
a class of question where keyword retrieval scores 0.00 out of 39 and expansion
scores 1.00. Both numbers are in `BENCHMARK.md`, with their caveats.

## Defects found and fixed

1. **`verified_at` to the second was not precise enough.** Truncating the timestamp
   put the stamp up to a second *behind* the file it had just verified, so a fact
   read as stale the instant it was written. Full precision fixed it. Caught by a
   test that asserted a fresh fact is not stale.

2. **Every "live record" filter had to learn a second exclusion.** Consolidation
   introduced `consolidated_into`, and six separate queries selected on
   `superseded_by=''` alone. Missing one would have leaked folded episodes back
   into recall.

3. **The benchmark could not measure the feature.** Adding graph expansion and
   re-running `run_recall.py` produced an identical 0.70, which looks like failure
   and is actually a blind spot in the instrument. Writing a second benchmark was
   the fix; pretending the first one had ruled on it would have been the error.

4. **A test that could never pass.** The re-verification test set the source file's
   mtime 120 seconds into the *future*, so no amount of re-verifying could clear
   the staleness. Correct behaviour, impossible fixture.

## Environment notes

- `python3-venv` is not installed here, so the clean-room install was built with
  `uv venv`. The package itself is plain setuptools and needs neither.
- `pip install -e .` fails under pip 22's build isolation, which resolves an old
  setuptools without PEP 660. `--no-build-isolation` with a current setuptools
  works. The `build-system` floor is now `setuptools>=64`.

## Known limits (carried into Phase 6)

- Graph expansion is **one hop**. Two hops would widen the net and the ranking
  has not been tuned for that.
- Expansion scans one column across all live records. Fine into five figures;
  past that it needs an index on `ref_files`.
- Staleness is per *file*, not per line. A record sourced at `auth.py:40` is stale
  when any part of `auth.py` changes.
- Consolidation groups by calendar month and summarises by first line only. It
  does not read the episodes and write prose about them.
- A record whose source path no longer resolves loses its anchor silently on
  reindex — it is not flagged as having lost one.
