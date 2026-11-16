"""Impact: union of sources, honest about which found what."""
from nexus.impact import analyze


def test_graph_and_text_agree_on_a_direct_dependent(graph_repo):
    imp = analyze(graph_repo, "a.py")
    by_file = {d.file: d for d in imp.dependents}
    assert "b.py" in by_file
    assert by_file["b.py"].strength == "strong"
    assert "graph" in by_file["b.py"].sources


def test_transitive_dependent_is_graph_only(graph_repo):
    """c.py never mentions a.py — only the graph can connect them."""
    imp = analyze(graph_repo, "a.py", depth=2)
    c = {d.file: d for d in imp.dependents}["c.py"]
    assert c.hops == 2
    assert c.sources == {"graph"}


def test_depth_1_does_not_reach_the_transitive_dependent(graph_repo):
    assert "c.py" not in {d.file for d in analyze(graph_repo, "a.py", depth=1).dependents}


def test_without_a_graph_it_says_so_and_still_answers(graph_repo):
    imp = analyze(graph_repo, "a.py", use_graph=False)
    assert imp.graph_available is False
    assert "b.py" in {d.file for d in imp.dependents}      # text found it
    assert all(d.strength != "strong" for d in imp.dependents)
    assert "text-only evidence" in imp.reason()


def test_weak_text_hits_do_not_inflate_blast_radius(graph_repo):
    """A name collision must not promote a file into the blast radius."""
    (graph_repo / "unrelated.py").write_text("def alpha():\n    return 'a different alpha'\n")
    imp = analyze(graph_repo, "a.py")
    assert "unrelated.py" in {d.file for d in imp.dependents}          # reported
    assert "unrelated.py" not in [d.file for d in imp.code_dependents]  # but not counted


def test_small_change_earns_the_light_workflow(graph_repo):
    imp = analyze(graph_repo, "a.py")
    assert imp.blast_radius < 3
    assert imp.gear == "light"


def test_risky_path_forces_the_full_workflow(graph_repo):
    (graph_repo / "migrations").mkdir()
    (graph_repo / "migrations" / "0001_initial.py").write_text("def up(): pass\n")
    imp = analyze(graph_repo, "migrations/0001_initial.py")
    assert imp.gear == "full" and "risky" in imp.reason()


def test_a_stale_graph_forces_the_full_workflow(graph_repo):
    import os
    import time
    os.utime(graph_repo / "b.py", (time.time() + 60, time.time() + 60))
    imp = analyze(graph_repo, "a.py")
    assert imp.gear == "full" and "stale" in imp.reason()


def test_tests_are_tagged_as_tests(graph_repo):
    (graph_repo / "test_a.py").write_text("from a import alpha\n\ndef test_alpha(): assert alpha()\n")
    imp = analyze(graph_repo, "a.py")
    assert "test_a.py" in imp.test_files


def test_unknown_target_is_reported_not_guessed(graph_repo):
    imp = analyze(graph_repo, "ghost.py")
    assert any("not in the graph" in n for n in imp.notes)
