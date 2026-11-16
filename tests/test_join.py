"""Phase 5 AC1 and AC2: the memory-to-graph join, in both directions.

`BLUEPRINT.md §5` specified retrieval as keyword match **plus graph expansion**.
Only the keyword half existed through Phase 4. These tests pin the other half.
"""
import pytest

from nexus.record import Record
from nexus.store import Store


@pytest.fixture
def joined(graph_repo, monkeypatch, tmp_path):
    """c.py -> b.py -> a.py. A fact about a.py, worded so that nothing in it
    overlaps with a question about b.py."""
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    (graph_repo / "docs").mkdir(exist_ok=True)
    (graph_repo / "docs" / "release.md").write_text("# Releases\n")
    store = Store.init(graph_repo)
    store.write(Record(
        name="first-routine-contract", type="project",
        body="The earliest helper yields a whole number and callers depend on that.",
        confidence="verified", source="a.py:1"))
    store.write(Record(
        name="unrelated-deployment-note", type="project",
        body="Releases go out on Tuesdays after the soak period.",
        confidence="observed", source="docs/release.md"))
    return store


# ---------- AC2: graph_refs populate themselves ----------

def test_a_source_path_links_the_record_to_its_graph_nodes(joined):
    rec = joined.recall("earliest helper whole number")[0]
    assert rec["graph_refs"], "a record sourced at a.py should carry a.py's node ids"
    assert "a_alpha" in rec["graph_refs"]


def test_ref_files_records_the_anchor_file(joined):
    import json
    row = joined.get("first-routine-contract")
    assert json.loads(row["ref_files"]) == ["a.py"]


def test_a_source_with_no_resolvable_path_invents_nothing(joined):
    _, rec, _ = joined.write(Record(name="from-a-commit", type="project",
                                    body="The retry count was raised.",
                                    confidence="verified", source="commit a1b2c3d"))
    assert rec.graph_refs == []


def test_a_source_file_outside_the_graph_still_anchors_by_path(joined):
    import json
    row = joined.get("unrelated-deployment-note")
    assert json.loads(row["ref_files"]) == ["docs/release.md"]
    assert json.loads(row["graph_refs"]) == []


def test_explicit_graph_refs_are_never_overwritten(joined):
    _, rec, _ = joined.write(Record(name="hand-linked", type="project", body="Manual link.",
                                    confidence="observed", source="a.py:1",
                                    graph_refs=["chosen_by_hand"]))
    assert rec.graph_refs == ["chosen_by_hand"]


# ---------- AC1: a keyword-invisible answer is still retrieved ----------

def test_the_question_names_a_neighbour_and_the_answer_arrives_anyway(joined):
    """`beta` appears nowhere in the record — not in its body, name or source.
    It is a symbol in b.py, and b.py calls a.py, which the record is about."""
    results = joined.recall("beta", limit=5)
    names = [r["name"] for r in results]
    assert "first-routine-contract" in names[:5]
    hit = next(r for r in results if r["name"] == "first-routine-contract")
    assert hit["via"] == "graph"
    assert "a.py" in hit["matched_files"]


def test_without_expansion_that_answer_is_invisible(joined):
    """Proves the graph did the work, not the keyword index."""
    names = [r["name"] for r in joined.recall("beta", limit=5, expand=False)]
    assert "first-routine-contract" not in names


def test_graph_hits_never_outrank_keyword_hits(joined):
    results = joined.recall("earliest helper beta", limit=5)
    vias = [r["via"] for r in results]
    assert vias == sorted(vias, key=lambda v: 0 if v == "keyword" else 1)


def test_expansion_does_not_drag_in_unconnected_records(joined):
    names = [r["name"] for r in joined.recall("beta", limit=10)]
    assert "unrelated-deployment-note" not in names


def test_a_project_with_no_graph_still_recalls(tmp_path, monkeypatch):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    store = Store.init(tmp_path / "plain")
    store.write(Record(name="x", type="project", body="A fact with no graph behind it."))
    assert store.graph() is None
    assert [r["name"] for r in store.recall("fact no graph")] == ["x"]


def test_neighbour_files_are_empty_when_the_query_names_nothing(joined):
    assert joined.graph_neighbour_files("tuesday release soak") == set()


def test_reindex_rebuilds_the_anchors_too(joined):
    import json
    joined.reindex()
    assert json.loads(joined.get("first-routine-contract")["ref_files"]) == ["a.py"]
    assert "first-routine-contract" in [r["name"] for r in joined.recall("beta", limit=5)]


# ---------- AC3: a verified fact knows when its ground has moved ----------

def test_a_fresh_verified_fact_is_not_stale(joined):
    assert joined.recall("earliest helper whole number")[0]["stale"] is None


def test_editing_the_source_file_makes_the_fact_stale(joined, graph_repo):
    (graph_repo / "a.py").write_text("def alpha():\n    return 'now a string'\n")
    hit = joined.recall("earliest helper whole number")[0]
    assert hit["stale"] and "changed after this was verified" in hit["stale"]


def test_deleting_the_source_file_makes_the_fact_stale(joined, graph_repo):
    (graph_repo / "a.py").unlink()
    assert "no longer exists" in joined.recall("earliest helper whole number")[0]["stale"]


def test_re_verifying_clears_the_staleness(joined, graph_repo):
    (graph_repo / "a.py").write_text("def alpha():\n    return 2\n")
    assert joined.recall("earliest helper whole number")[0]["stale"]

    joined.write(Record(name="first-routine-contract", type="project",
                        body="The earliest helper yields a whole number, re-checked after the edit.",
                        confidence="verified", source="a.py:1"))
    assert joined.recall("earliest helper whole number")[0]["stale"] is None


def test_observed_and_assumed_facts_never_claim_currency(joined, graph_repo):
    joined.write(Record(name="a-guess", type="project", body="Probably two retries.",
                        confidence="assumed", source="a.py:1"))
    (graph_repo / "a.py").write_text("def alpha():\n    return 3\n")
    hit = next(r for r in joined.recall("probably two retries") if r["name"] == "a-guess")
    assert hit["stale"] is None


def test_status_counts_stale_facts_and_names_them(joined, graph_repo):
    (graph_repo / "a.py").write_text("def alpha():\n    return 4\n")
    stats = joined.stats()
    assert stats["stale"] == 1
    assert stats["stale_records"][0]["name"] == "first-routine-contract"


def test_a_fact_anchored_to_nothing_is_never_stale(joined):
    joined.write(Record(name="from-a-commit-2", type="project", body="Retries were raised to five.",
                        confidence="verified", source="commit deadbeef"))
    hit = next(r for r in joined.recall("retries raised five") if r["name"] == "from-a-commit-2")
    assert hit["stale"] is None


def test_verified_at_is_precise_to_the_second(joined):
    """A date alone cannot distinguish 'verified this morning' from 'edited this
    afternoon', so same-day edits would be missed."""
    row = joined.get("first-routine-contract")
    assert "T" in row["verified_at"], row["verified_at"]


def test_touching_a_file_without_changing_it_is_not_stale(joined, graph_repo):
    """A checkout, a rebuild or a formatter run moves mtime without changing
    content. A staleness warning that fires on those is noise, and noise is
    the failure mode that gets a check switched off."""
    import os
    import time
    future = time.time() + 300
    os.utime(graph_repo / "a.py", (future, future))
    assert joined.recall("earliest helper whole number")[0]["stale"] is None


def test_staleness_falls_back_to_mtime_for_a_record_with_no_anchor(joined, graph_repo):
    """Records written before anchor hashes existed must still be checkable."""
    import os
    import time
    row = joined.get("first-routine-contract")
    joined.db.execute("UPDATE records SET anchor_hash='' WHERE id=?", (row["id"],))
    joined.db.commit()
    future = time.time() + 300
    os.utime(graph_repo / "a.py", (future, future))
    why = joined.record_staleness(dict(joined.get("first-routine-contract")))
    assert why and "mtime only" in why
