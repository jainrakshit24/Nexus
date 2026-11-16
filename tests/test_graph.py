"""AC3: staleness is detected from disk, without rebuilding the graph."""
import os
import time

from nexus.graph import GraphMissing, load


def test_loads_and_indexes(graph_repo):
    g = load(graph_repo)
    assert len(g.nodes) == 4
    assert g.directed is True
    assert sorted(g.by_file) == ["a.py", "b.py", "c.py", "d.py"]


def test_missing_graph_says_how_to_build_one(tmp_path):
    try:
        load(tmp_path)
    except GraphMissing as e:
        assert "/graphify" in str(e)
    else:
        raise AssertionError("expected GraphMissing")


def test_direct_dependents(graph_repo):
    g = load(graph_repo)
    _, ids = g.resolve("a.py")
    files = {d["file"] for d in g.dependents(ids)}
    assert files == {"b.py"}


def test_structural_edges_are_not_dependencies(graph_repo):
    """`contains` means a file holds a symbol, not that it depends on one."""
    g = load(graph_repo)
    _, ids = g.resolve("a.py")
    assert "d.py" not in {d["file"] for d in g.dependents(ids, depth=3)}


def test_transitive_dependents_at_depth_2(graph_repo):
    g = load(graph_repo)
    _, ids = g.resolve("a.py")
    deps = {d["file"]: d["hops"] for d in g.dependents(ids, depth=2)}
    assert deps == {"b.py": 1, "c.py": 2}


def test_resolve_by_symbol_and_by_suffix(graph_repo):
    g = load(graph_repo)
    assert g.resolve("alpha") == ("symbol", ["a_alpha"])
    assert g.resolve("nope.py")[0] == "none"


def test_fresh_graph_reports_fresh(graph_repo):
    assert load(graph_repo).staleness(graph_repo).is_stale is False


def test_touching_a_file_makes_the_graph_stale_without_rebuilding(graph_repo):
    g = load(graph_repo)
    target = graph_repo / "b.py"
    os.utime(target, (time.time() + 60, time.time() + 60))
    s = g.staleness(graph_repo)          # same loaded graph, no rebuild
    assert s.is_stale and s.changed == ["b.py"]
    assert "STALE" in s.summary()


def test_deleted_and_unindexed_files_are_reported(graph_repo):
    (graph_repo / "d.py").unlink()
    (graph_repo / "e.py").write_text("def eps(): pass\n")
    s = load(graph_repo).staleness(graph_repo, extensions={".py"})
    assert s.deleted == ["d.py"]
    assert s.unindexed == ["e.py"]


def test_graph_root_is_read_from_marker(graph_repo):
    assert load(graph_repo).graph_root == graph_repo
