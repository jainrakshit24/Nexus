# ADR 0002 — Defer local embeddings; the pre-registered trigger did not fire

**Date:** 2026-11-16 · **Status:** accepted

## Context

`docs/BLUEPRINT.md §5` committed, before any measurement, to a single rule:

> *if recall@5 on a 50-question benchmark drops below 0.7, add local embeddings
> (`sqlite-vec` + a small local model) — not a hosted vector DB.*

Phase 2 measured **0.64**, a one-line tokenizer change (`porter unicode61`) lifted
it to **0.70**, and Phases 2, 3 and 4 each deferred the decision. Phase 5 was
supposed to close it.

Phase 5 then built the half of the design that had never existed: graph expansion
in retrieval (`BLUEPRINT.md §5` specified "keyword match **plus** graph expansion";
only the first half was implemented). Two benchmarks now exist, and they measure
different things.

## Measurements

| Benchmark | What it asks | recall@5 |
|---|---|---|
| `bench/run_recall.py` | 50 facts with **no code behind them**, questions that paraphrase | **0.70** — unchanged by graph expansion |
| `bench/run_graph_recall.py` | 40 facts **anchored to files**, each question naming the caller of the module it asks about | **0.00 → 1.00** with expansion |

The paraphrase benchmark is unchanged because its facts are anchored to nothing;
there is no graph for expansion to traverse. That is a property of the benchmark,
not a failure of the feature.

## Decision

**Do not add embeddings now.** Keep hybrid keyword + graph retrieval.

The rule was registered in advance and says *below* 0.7. The measurement is 0.70.
It did not fire. Moving the threshold after seeing the number would make the
pre-registration worthless, which was the entire point of writing it down first.

## Alternatives considered

- **Add embeddings anyway**, on the grounds that 0.70 is a tie rather than a pass.
  Rejected: it means a new dependency (`model2vec` or `fastembed`), a model
  download of tens of megabytes, and a second index to keep in sync — against a
  threshold that, by the project's own rule, was not crossed. None of those costs
  were approved by anyone.
- **Loosen the benchmark** so the number improves. Rejected outright: that is
  tuning the ruler.
- **Treat graph expansion as having solved it.** Rejected: it solves a different
  class of question. It cannot help a fact that is anchored to no file, and the
  paraphrase benchmark proves exactly that.

## Consequences

- **Good:** no new dependency, no model download, no second index, local-first
  operation preserved. The graph join covers the structural questions keyword
  search never could.
- **Bad:** a question phrased entirely in different words from an *unanchored*
  fact still misses roughly one time in three. That is a real, measured gap.
- **Honest:** nothing here claims the retrieval problem is solved.

## What reopens this

Any one of these, and the decision is revisited with the number attached:

1. `bench/run_recall.py` reports recall@5 **below 0.70** on a corpus of real
   project facts rather than fixtures.
2. A user reports that recall misses things they know are stored — the benchmark
   is a proxy, and a proxy that disagrees with the user is the proxy that is wrong.
3. The corpus passes a few thousand records, where keyword ranking degrades and
   the cost of an index becomes proportionally smaller.

## Affects

- `nexus/store.py` — `recall`, `graph_neighbour_files`, `records_anchored_to`
- `bench/run_recall.py`, `bench/run_graph_recall.py`
