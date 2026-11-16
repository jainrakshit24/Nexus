#!/usr/bin/env python3
"""What graph expansion adds, measured on questions the keyword benchmark cannot contain.

`bench/run_recall.py` stores facts with no code behind them, so graph expansion
has nothing to traverse there. This benchmark builds a real (synthetic) package,
anchors every fact to a file, and asks each question by naming a *neighbouring*
symbol — a word that appears nowhere in the answer.

Same corpus, same questions, run twice: expansion off, then on. The difference
is the graph's contribution and nothing else.

Usage: python3 bench/run_graph_recall.py [--modules 40]
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nexus.store as store_mod  # noqa: E402
from nexus.record import Record  # noqa: E402
from nexus.store import Store  # noqa: E402

# Facts are phrased so they share no vocabulary with the symbol names used to ask.
TOPICS = [
    "retains the original ordering of its input",
    "treats an empty payload as a no-op rather than an error",
    "rounds half away from zero, not to even",
    "caps the batch at one thousand entries",
    "is the only writer to the ledger",
    "assumes the clock is monotonic",
    "was rewritten to avoid a quadratic scan",
    "keeps a bounded cache of the last two hundred keys",
    "must stay reentrant for the scheduler",
    "silently drops duplicates by design",
]


def build(root: Path, modules: int) -> None:
    pkg = root / "src"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").touch()
    for i in range(modules):
        prev = f"from .mod{i-1} import step_{i-1}\n" if i else ""
        call = f"    step_{i-1}(x)\n" if i else "    pass\n"
        (pkg / f"mod{i}.py").write_text(
            f'"""Module {i}."""\n{prev}\n\ndef step_{i}(x):\n{call}\n')


def fake_graph(root: Path, modules: int) -> None:
    """A graphify-shaped graph for the chain mod(i) -> mod(i-1)."""
    out = root / "graphify-out"
    out.mkdir(parents=True, exist_ok=True)
    nodes = [{"id": f"step_{i}", "label": f"step_{i}",
              "source_file": f"src/mod{i}.py", "source_location": "L4"}
             for i in range(modules)]
    links = [{"source": f"step_{i}", "target": f"step_{i-1}", "relation": "calls",
              "_origin": "ast"} for i in range(1, modules)]
    (out / "graph.json").write_text(json.dumps(
        {"directed": True, "multigraph": False, "graph": {}, "nodes": nodes, "links": links}))
    (out / ".graphify_root").write_text(str(root))
    (out / "manifest.json").write_text(json.dumps(
        {f"src/mod{i}.py": {"mtime": (root / "src" / f"mod{i}.py").stat().st_mtime,
                            "ast_hash": "x"} for i in range(modules)}))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modules", type=int, default=40)
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="nexus-graphbench-"))
    root = tmp / "repo"
    build(root, args.modules)
    fake_graph(root, args.modules)

    store_mod.GLOBAL_DIR = tmp / "global"
    store = Store.init(root)

    # One fact per module, anchored to that module's file.
    for i in range(args.modules):
        store.write(Record(
            name=f"mod{i}-behaviour", type="project",
            body=f"This routine {TOPICS[i % len(TOPICS)]}.",
            confidence="observed", source=f"src/mod{i}.py:4"))

    # Ask about module i by naming its *caller's* symbol, step_(i+1), which appears
    # nowhere in the answer. Only the graph connects the two.
    questions = [(f"step_{i+1}", f"mod{i}-behaviour") for i in range(args.modules - 1)]

    def measure(expand: bool):
        hits = {1: 0, 3: 0, 5: 0}
        lat = []
        for q, expected in questions:
            t0 = time.perf_counter()
            names = [r["name"] for r in store.recall(q, limit=5, expand=expand)]
            lat.append((time.perf_counter() - t0) * 1000)
            for k in hits:
                if expected in names[:k]:
                    hits[k] += 1
        return hits, lat

    print(f"corpus   : {args.modules} modules, {args.modules} anchored facts")
    print(f"questions: {len(questions)} — each names the caller of the module it asks about,")
    print( "            a symbol that appears in no fact's text\n")

    total = len(questions)
    for label, expand in (("keyword only (expand=False)", False), ("keyword + graph (expand=True)", True)):
        hits, lat = measure(expand)
        line = "  ".join(f"recall@{k} {hits[k]/total:.2f}" for k in (1, 3, 5))
        print(f"{label:<32} {line}   p50 {statistics.median(lat):.1f} ms")

    off, _ = measure(False)
    on, _ = measure(True)
    print(f"\ngraph contribution at k=5: {off[5]/total:.2f} -> {on[5]/total:.2f} "
          f"(+{(on[5]-off[5])/total:.2f})")

    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
