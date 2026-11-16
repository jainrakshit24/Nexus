import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus.store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    # Keep global-tier records inside the tmp dir so tests never touch ~/.nexus
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    return Store.init(tmp_path / "repo")


@pytest.fixture
def graph_repo(tmp_path):
    """A tiny repo plus a hand-built graphify-out, so graph tests are deterministic.

    Shape: c.py -> b.py -> a.py (imports), d.py is unrelated.
    Nothing in c.py mentions a.py, so it is reachable only at depth 2.
    """
    import json
    import time

    root = tmp_path / "proj"
    (root / "graphify-out").mkdir(parents=True)
    (root / "a.py").write_text("def alpha():\n    return 1\n")
    (root / "b.py").write_text("from a import alpha\n\ndef beta():\n    return alpha() + 1\n")
    (root / "c.py").write_text("from b import beta\n\ndef gamma():\n    return beta() * 2\n")
    (root / "d.py").write_text("def delta():\n    return 0\n")

    nodes = [
        {"id": "a_alpha", "label": "alpha", "source_file": "a.py", "source_location": "L1"},
        {"id": "b_beta", "label": "beta", "source_file": "b.py", "source_location": "L3"},
        {"id": "c_gamma", "label": "gamma", "source_file": "c.py", "source_location": "L3"},
        {"id": "d_delta", "label": "delta", "source_file": "d.py", "source_location": "L1"},
    ]
    links = [
        {"source": "b_beta", "target": "a_alpha", "relation": "calls", "_origin": "ast"},
        {"source": "c_gamma", "target": "b_beta", "relation": "calls", "_origin": "ast"},
        # structural, must NOT count as a dependency
        {"source": "d_delta", "target": "a_alpha", "relation": "contains", "_origin": "ast"},
    ]
    (root / "graphify-out" / "graph.json").write_text(json.dumps(
        {"directed": True, "multigraph": False, "graph": {}, "nodes": nodes, "links": links}))
    (root / "graphify-out" / ".graphify_root").write_text(str(root))
    now = time.time()
    (root / "graphify-out" / "manifest.json").write_text(json.dumps(
        {f: {"mtime": now, "ast_hash": "x"} for f in ("a.py", "b.py", "c.py", "d.py")}))
    return root
