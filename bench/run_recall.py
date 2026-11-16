#!/usr/bin/env python3
"""Measure recall@k for `nexus recall` on a paraphrase benchmark.

Questions deliberately avoid the fact's own distinctive words, because
that is the case keyword retrieval finds hard. Whatever the number is, it
goes into docs/BENCHMARK.md unedited — it decides whether Phase 2's
upgrade trigger (add local embeddings below recall@5 of 0.7) fires.

Usage: python3 bench/run_recall.py
"""
from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nexus.store as store_mod  # noqa: E402
from nexus.record import Record  # noqa: E402
from nexus.store import Store  # noqa: E402

DATA = json.loads((Path(__file__).parent / "recall_dataset.json").read_text())


def build_store(tmp: Path) -> Store:
    store_mod.GLOBAL_DIR = tmp / "global"
    store = Store.init(tmp / "repo")
    for name, body in DATA["facts"]:
        store.write(Record(name=name, type="project", body=body,
                           confidence="observed", source="benchmark fixture"))
    return store


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    store = build_store(tmp)

    ks = (1, 3, 5, 10)
    hits = {k: 0 for k in ks}
    latencies: list[float] = []
    misses: list[tuple[str, str, list[str]]] = []

    for question, expected in DATA["questions"]:
        t0 = time.perf_counter()
        results = store.recall(question, limit=max(ks))
        latencies.append((time.perf_counter() - t0) * 1000)
        names = [r["name"] for r in results]
        for k in ks:
            if expected in names[:k]:
                hits[k] += 1
        if expected not in names[:5]:
            misses.append((question, expected, names[:3]))

    total = len(DATA["questions"])
    print(f"corpus   : {len(DATA['facts'])} facts")
    print(f"questions: {total} (paraphrased, not copied from the facts)")
    for k in ks:
        print(f"recall@{k:<2}: {hits[k]/total:.2f}  ({hits[k]}/{total})")
    print(f"latency  : p50 {statistics.median(latencies):.1f} ms, max {max(latencies):.1f} ms")
    print(f"\nmisses at k=5: {len(misses)}")
    for q, expected, got in misses:
        print(f"  {q!r}\n    wanted {expected}, top-3 {got}")

    trigger = hits[5] / total < 0.7
    print(f"\nupgrade trigger (recall@5 < 0.70): {'FIRED' if trigger else 'not fired'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
