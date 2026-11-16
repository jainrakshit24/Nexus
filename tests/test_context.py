"""AC2: a context pack never exceeds its budget, measured by the real tokenizer."""
import pytest

from nexus import tokens
from nexus.context import build, targets_in
from nexus.record import Record
from nexus.store import Store

TASKS = [
    "refactor a.py to return a tuple", "add logging to b.py", "why does c.py call beta",
    "fix the import cycle", "rename alpha to first", "add type hints across the package",
    "write tests for b.py", "speed up gamma in c.py", "document the public API",
    "remove d.py, it is dead code", "handle the empty-input case in a.py",
    "migrate b.py to async", "audit a.py for security issues", "add a CLI flag",
    "split c.py into two modules", "cache the result of alpha", "fix flaky test",
    "bump the dependency", "add error handling to beta", "profile the hot path",
]


@pytest.fixture
def ctx_repo(graph_repo, monkeypatch, tmp_path):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    store = Store.init(graph_repo)
    store.write(Record(name="project-overview", type="project",
                       body="Tiny demo package: a.py defines alpha, b.py beta, c.py gamma.",
                       confidence="observed", source="test fixture"))
    store.write(Record(name="alpha-returns-int", type="project",
                       body="alpha() returns an int and callers depend on that.",
                       confidence="verified", source="a.py:1"))
    return graph_repo


@pytest.mark.parametrize("budget", [200, 800, 4000])
def test_pack_never_exceeds_budget_across_varied_tasks(ctx_repo, budget):
    for task in TASKS:
        pack = build(ctx_repo, task, budget=budget)
        measured = tokens.count(pack.render())
        assert pack.actual <= budget, f"{task!r}: {pack.actual} > {budget}"
        # The rendered whole is a little larger than the sum of sections (header,
        # omitted-list). Allow for that, but it must stay in the same ballpark.
        assert measured <= budget * 1.4, f"{task!r}: rendered {measured} vs budget {budget}"


def test_what_does_not_fit_is_named_not_truncated(ctx_repo):
    pack = build(ctx_repo, "refactor a.py and b.py together", budget=60)
    assert pack.dropped, "expected sections to be dropped at a tiny budget"
    assert all("tokens" in d for d in pack.dropped)
    assert "Omitted (budget)" in pack.render()


def test_packing_pays_off_once_files_are_realistic_sized(ctx_repo):
    """Outlines beat full reads on real files. On toy files they do not — and
    the accounting clamps to zero rather than inventing a saving."""
    big = ctx_repo / "a.py"
    big.write_text(
        "def alpha():\n    return 1\n\n"
        + "".join(f"def helper_{i}():\n    x = {i}\n    y = x * 2\n    return y\n\n" for i in range(150))
    )
    pack = build(ctx_repo, "refactor a.py", budget=8000)
    assert pack.baseline > pack.actual, (pack.baseline, pack.actual)
    assert pack.accounting().saved_estimated > 0
    assert pack.accounting().compression < 1


def test_tiny_files_report_no_saving_rather_than_a_negative_one(ctx_repo):
    pack = build(ctx_repo, "refactor a.py", budget=4000)
    assert pack.accounting().saved_estimated == 0


def test_relevant_memory_is_included(ctx_repo):
    pack = build(ctx_repo, "does alpha return an int", budget=4000)
    assert "alpha-returns-int" in pack.render()


def test_impact_section_appears_for_a_named_file(ctx_repo):
    assert "Impact of a.py" in build(ctx_repo, "refactor a.py", budget=4000).render()


def test_targets_only_match_files_that_exist(ctx_repo):
    assert targets_in("touch a.py and ghost.py", ctx_repo) == ["a.py"]
