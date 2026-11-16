"""Phase 5 AC5: episodic memory decays into summaries without losing anything."""
from datetime import date, timedelta

import pytest

from nexus.record import Record
from nexus.store import Store


@pytest.fixture
def episodic(tmp_path, monkeypatch):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    store = Store.init(tmp_path / "repo")
    old = (date.today() - timedelta(days=90)).isoformat()
    for i in range(5):
        store.write(Record(name=f"old-episode-{i}", type="episodic",
                           body=f"Chased a null pointer in handler {i}.",
                           confidence="observed", created_at=old))
    store.write(Record(name="recent-episode", type="episodic",
                       body="Fixed the flaky timeout test today.", confidence="observed"))
    return store


def test_old_episodes_fold_into_one_summary(episodic):
    results = episodic.consolidate_episodes(older_than_days=30)
    assert len(results) == 1 and results[0]["folded"] == 5


def test_nothing_is_deleted(episodic, tmp_path):
    episodic.consolidate_episodes(older_than_days=30)
    kept = list((tmp_path / "repo" / ".nexus" / "episodes").rglob("old-episode-*.md"))
    assert len(kept) == 5


def test_folded_records_leave_default_recall(episodic):
    assert episodic.recall("null pointer handler")
    episodic.consolidate_episodes(older_than_days=30)
    names = [r["name"] for r in episodic.recall("null pointer handler")]
    assert not any(n.startswith("old-episode") for n in names)


def test_folded_records_are_still_reachable(episodic):
    episodic.consolidate_episodes(older_than_days=30)
    names = [r["name"] for r in episodic.recall("null pointer handler", include_superseded=True)]
    assert any(n.startswith("old-episode") for n in names)


def test_the_summary_lists_what_it_folded(episodic):
    episodic.consolidate_episodes(older_than_days=30)
    summary = episodic.recall("episodes folded originals", type_="episodic")[0]
    from pathlib import Path
    body = Path(summary["path"]).read_text()
    for i in range(5):
        assert f"old-episode-{i}" in body


def test_recent_episodes_are_left_alone(episodic):
    episodic.consolidate_episodes(older_than_days=30)
    assert "recent-episode" in [r["name"] for r in episodic.recall("flaky timeout test")]


def test_a_dry_run_changes_nothing(episodic):
    results = episodic.consolidate_episodes(older_than_days=30, dry_run=True)
    assert results[0]["folded"] == 5
    assert episodic.recall("null pointer handler")          # still in default recall
    assert episodic.stats()["consolidated"] == 0


def test_a_second_pass_finds_nothing_to_do(episodic):
    episodic.consolidate_episodes(older_than_days=30)
    assert episodic.consolidate_episodes(older_than_days=30) == []


def test_a_summary_is_never_folded_into_another_summary(episodic):
    episodic.consolidate_episodes(older_than_days=30)
    # Age the summary itself, then run again.
    from nexus.record import read as read_record
    old = (date.today() - timedelta(days=200)).isoformat()
    for p in (episodic.dir / "episodes").rglob("episodes-*.md"):
        rec = read_record(p)
        rec.created_at = old
        rec.write(p)
        episodic._index(rec, p)
    episodic.db.commit()
    assert episodic.consolidate_episodes(older_than_days=30) == []


def test_a_single_old_episode_is_left_as_is(tmp_path, monkeypatch):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    store = Store.init(tmp_path / "repo")
    store.write(Record(name="lonely", type="episodic", body="One thing happened.",
                       confidence="observed",
                       created_at=(date.today() - timedelta(days=90)).isoformat()))
    assert store.consolidate_episodes(older_than_days=30) == []


def test_stats_counts_consolidated_records(episodic):
    episodic.consolidate_episodes(older_than_days=30)
    s = episodic.stats()
    assert s["consolidated"] == 5
    assert s["by_type"]["episodic"] == 2    # the summary and the recent one
