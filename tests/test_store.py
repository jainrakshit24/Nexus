"""AC2, AC4, AC5: recall speed, index rebuildability, supersede chains."""
import time

import pytest

from nexus.record import Record
from nexus.store import Store


def make(store: Store, n: int) -> None:
    words = ["auth", "payment", "schema", "cache", "queue", "webhook", "migration", "index"]
    for i in range(n):
        store.write(Record(
            name=f"fact-{i}",
            type="project",
            body=f"Record {i} concerns the {words[i % len(words)]} subsystem and its behaviour.",
            confidence="observed",
            source=f"src/mod{i % 20}.py:{i}",
        ))


def test_recall_under_300ms_on_500_records(store: Store):
    make(store, 500)
    store.recall("auth")  # warm the connection, not the result
    t0 = time.perf_counter()
    results = store.recall("payment subsystem", limit=10)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert results, "expected matches"
    assert elapsed_ms < 300, f"recall took {elapsed_ms:.1f} ms"


def test_reindex_reproduces_identical_recall(store: Store):
    make(store, 60)
    before = [(r["id"], round(r["score"], 9)) for r in store.recall("schema subsystem", limit=10)]
    store.db_path.unlink()
    store._db = None
    assert store.reindex() == 60
    after = [(r["id"], round(r["score"], 9)) for r in store.recall("schema subsystem", limit=10)]
    assert before == after


def test_identical_rewrite_is_a_noop(store: Store):
    args = {"name": "stack", "type": "project", "body": "The API is FastAPI.",
            "confidence": "observed"}
    assert store.write(Record(**args))[0] == "created"
    assert store.write(Record(**args))[0] == "unchanged"
    assert store.stats()["live"] == 1


def test_conflict_supersedes_and_keeps_history(store: Store):
    store.write(Record(name="db", type="project", body="The database is MySQL.",
                       confidence="verified", source="requirements.txt:3"))
    action, new, _ = store.write(Record(name="db", type="project", body="The database is Postgres.",
                                        confidence="verified", source="commit abc123"))
    assert action == "superseded"

    live = store.recall("database", limit=10)
    assert len(live) == 1
    assert "Postgres" in (store.root / ".nexus" / "project" / "db.md").read_text()

    chain = store.chain(new.id)
    assert len(chain) == 2
    assert chain[1]["superseded_by"] == new.id
    old_file = store.dir / "superseded" / f"db.{chain[1]['id']}.md"
    assert old_file.exists() and "MySQL" in old_file.read_text()

    assert len(store.recall("database", limit=10, include_superseded=True)) == 2


def test_verified_requires_a_source():
    with pytest.raises(ValueError, match="requires --source"):
        Record(name="x", type="project", body="b", confidence="verified")


def test_assumption_ranks_below_verified_on_equal_text(store: Store):
    body = "The retry limit for the webhook dispatcher is three attempts."
    store.write(Record(name="retry-assumed", type="project", body=body, confidence="assumed"))
    store.write(Record(name="retry-verified", type="project", body=body,
                       confidence="verified", source="src/dispatch.py:88"))
    names = [r["name"] for r in store.recall("retry limit webhook dispatcher")]
    assert names.index("retry-verified") < names.index("retry-assumed")


def test_forget_is_soft_by_default(store: Store):
    _, rec, _ = store.write(Record(name="temp", type="project", body="A passing thought."))
    assert store.forget("temp") == "forgotten"
    assert store.recall("passing thought") == []
    assert (store.dir / "superseded" / f"temp.{rec.id}.md").exists()


def test_forget_hard_deletes(store: Store):
    _, rec, _ = store.write(Record(name="temp2", type="project", body="Another thought."))
    assert store.forget("temp2", hard=True) == "deleted"
    assert not store.path_for(rec).exists()
    assert store.get("temp2") is None


def test_episodic_records_are_filed_by_month(store: Store):
    _, rec, _ = store.write(Record(name="debug-session", type="episodic",
                                   body="Chased a null pointer for an hour."))
    path = store.path_for(rec)
    assert path.parent.name == rec.created_at[:7]
    assert path.exists()


def test_an_index_from_an_older_schema_is_rebuilt_not_trusted(store: Store):
    """A stale tokenizer silently changes ranking, so the index must not be reused."""
    store.write(Record(name="a", type="project", body="Rate limiting happens at the gateway."))
    store.db.execute("PRAGMA user_version = 1")
    store.db.commit()
    store._db = None
    store._stale_schema = None

    fresh = Store(store.root)
    assert fresh.ensure_current_schema() == 1       # rebuilt one record
    assert fresh.recall("rate limiting")[0]["name"] == "a"
    assert fresh.ensure_current_schema() is None    # already current, no second rebuild


def test_stemming_matches_a_different_word_form(store: Store):
    store.write(Record(name="deploys", type="project",
                       body="Deployments are blue green with a soak period."))
    assert [r["name"] for r in store.recall("deployment")] == ["deploys"]


def test_a_global_fact_written_in_one_project_is_visible_in_another(tmp_path, monkeypatch):
    """The global tier is shared by every project, but each project owns its index.
    Without a sync this tier looked implemented and silently was not: the fact
    stayed invisible everywhere else until somebody ran reindex by hand."""
    from nexus import store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")

    a = store_mod.Store.init(tmp_path / "a")
    b = store_mod.Store.init(tmp_path / "b")
    assert b.recall("tabs") == []

    a.write(Record(name="org-uses-tabs", type="global", confidence="verified",
                   source="team convention", body="We indent with tabs, never spaces."))

    hits = b.recall("tabs")
    assert [h["name"] for h in hits] == ["org-uses-tabs"]


def test_removing_a_global_fact_removes_it_from_other_projects_too(tmp_path, monkeypatch):
    from nexus import store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    a = store_mod.Store.init(tmp_path / "a")
    b = store_mod.Store.init(tmp_path / "b")
    _, rec, _ = a.write(Record(name="org-uses-tabs", type="global", confidence="verified",
                               source="team convention", body="Tabs, never spaces."))
    assert b.recall("tabs")

    a.path_for(rec).unlink()
    assert b.recall("tabs") == []
