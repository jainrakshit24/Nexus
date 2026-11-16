#!/usr/bin/env python3
"""Cold-start cost on a large repository.

The corpus is synthetic — 10,000 small Python modules in a realistic package
layout — because it has to be reproducible on any machine. Synthetic files are
smaller and more uniform than real ones, so treat these as a floor, not a
promise. Every number printed was timed by this script.

Usage: python3 bench/run_coldstart.py [--files 10000]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nexus.store as store_mod  # noqa: E402
from nexus import dashboard, discover, symbols  # noqa: E402
from nexus.impact import analyze  # noqa: E402
from nexus.mcpclient import MCPClient  # noqa: E402
from nexus.record import Record  # noqa: E402
from nexus.store import Store  # noqa: E402

PKG_ROOT = str(Path(__file__).resolve().parents[1])


def build_corpus(root: Path, n: int) -> float:
    t0 = time.perf_counter()
    (root / "tests").mkdir(parents=True, exist_ok=True)
    per_pkg = 100
    for i in range(n):
        pkg = root / "src" / f"pkg{i // per_pkg:03d}"
        pkg.mkdir(parents=True, exist_ok=True)
        (pkg / "__init__.py").touch()
        prev = f"from ..pkg{(i // per_pkg) - 1:03d}.mod{i - 1} import handler_{i - 1}\n" if i % per_pkg else ""
        (pkg / f"mod{i}.py").write_text(
            f'"""Module {i}."""\n{prev}\n\n'
            f"CONSTANT_{i} = {i}\n\n\n"
            f"def handler_{i}(payload):\n"
            f'    """Handle payload {i}."""\n'
            f"    return payload, CONSTANT_{i}\n\n\n"
            f"class Service{i}:\n"
            f"    def run(self):\n"
            f"        return handler_{i}(None)\n"
        )
    (root / "pyproject.toml").write_text("[project]\nname='big'\n")
    (root / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n")
    return time.perf_counter() - t0


def timed(label: str, fn):
    t0 = time.perf_counter()
    value = fn()
    dt = time.perf_counter() - t0
    print(f"{label:<44} {dt*1000:9.1f} ms")
    return value, dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--files", type=int, default=10000)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="nexus-bench-"))
    root = tmp / "bigrepo"
    print(f"building a synthetic {args.files:,}-file repo at {root} …")
    build_s = build_corpus(root, args.files)
    real_files = sum(1 for _ in root.rglob("*.py"))
    size_mb = sum(f.stat().st_size for f in root.rglob("*.py")) / 1e6
    print(f"corpus: {real_files:,} .py files, {size_mb:.1f} MB, built in {build_s:.1f}s\n")

    store_mod.GLOBAL_DIR = tmp / "global"

    print("--- cold start, nothing cached ---")
    (profile, _) = timed("discovery (nexus init: stack, tests, census)",
                         lambda: discover.profile(root))
    print(f"{'':<44} detected: {profile['stack']}, tests: {profile['test_command'] or 'none'}")

    store, _ = timed("store init + empty index", lambda: Store.init(root))

    def seed():
        for i in range(200):
            store.write(Record(name=f"fact-{i}", type="project",
                               body=f"Service {i} handles payload shape {i} and retries twice.",
                               confidence="observed", source=f"src/pkg{i//100:03d}/mod{i}.py:1"))
    timed("writing 200 memory records", seed)
    timed("first recall (warm index)", lambda: store.recall("payload retries"))

    target = f"src/pkg000/mod50.py"
    timed("symbol outline of one module", lambda: symbols.outline(root / target))
    (_, impact_s) = timed(f"impact on {target} (no graph: text over {real_files:,} files)",
                          lambda: analyze(root, target, use_graph=False))
    timed("dashboard state", lambda: dashboard.state(root))

    print("\n--- MCP server cold start (host launch to first answer) ---")
    env = {**os.environ, "PYTHONPATH": PKG_ROOT}
    cmd = [sys.executable, "-m", "nexus.server", "--root", str(root)]
    t0 = time.perf_counter()
    with MCPClient(cmd, cwd=str(root), timeout=120, env=env) as c:
        init_s = time.perf_counter() - t0
        print(f"{'launch + initialize':<44} {init_s*1000:9.1f} ms")
        t1 = time.perf_counter()
        c.tools()
        print(f"{'tools/list':<44} {(time.perf_counter()-t1)*1000:9.1f} ms")
        t2 = time.perf_counter()
        c.call("nexus_recall", {"query": "payload retries"})
        print(f"{'first nexus_recall over MCP':<44} {(time.perf_counter()-t2)*1000:9.1f} ms")

    print(f"\nnote: impact without a graph costs {impact_s:.1f}s on this corpus because it "
          f"reads every text file.\n      With a graph built, reverse-edge lookup is a dict "
          f"traversal and the text pass is the fallback, not the path.")

    if args.keep:
        print(f"\ncorpus kept at {root}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
