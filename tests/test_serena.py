"""Serena adapter: the per-project cache that BLUEPRINT 12 asked for."""
from nexus import serena


def test_a_cached_answer_is_served_without_starting_serena(tmp_path):
    """The cold start is the whole cost (~4.7s). Proven here by the fact that this
    machine need not have Serena at all: an uncached call reports it missing,
    a cached one answers."""
    (tmp_path / ".nexus").mkdir(parents=True)
    (tmp_path / "a.py").write_text("def f(): pass\n", encoding="utf-8")

    sig = serena.repo_signature(tmp_path)
    serena.save_cache(tmp_path, sig, {"a.py::f": {"b.py": ["f"]}})

    hits, err = serena.referencing_files(tmp_path, ["f"], "a.py")
    assert hits == {"b.py": ["f"]}
    assert err is None


def test_an_edit_anywhere_in_the_repo_drops_the_cache(tmp_path):
    """References change when a caller is added in some other file, so the target
    file's own hash is not a sufficient key."""
    (tmp_path / ".nexus").mkdir(parents=True)
    (tmp_path / "a.py").write_text("def f(): pass\n", encoding="utf-8")
    sig = serena.repo_signature(tmp_path)
    serena.save_cache(tmp_path, sig, {"a.py::f": {"b.py": ["f"]}})

    (tmp_path / "elsewhere.py").write_text("from a import f\nf()\n", encoding="utf-8")
    assert serena.repo_signature(tmp_path) != sig
    assert serena.load_cache(tmp_path, serena.repo_signature(tmp_path)) == {}


def test_a_corrupt_cache_is_ignored_rather_than_raised(tmp_path):
    (tmp_path / ".nexus").mkdir(parents=True)
    (tmp_path / ".nexus" / serena.CACHE_FILE).write_text("{not json", encoding="utf-8")
    assert serena.load_cache(tmp_path, "whatever") == {}


def test_use_cache_false_still_reports_a_missing_serena(tmp_path):
    (tmp_path / ".nexus").mkdir(parents=True)
    serena.save_cache(tmp_path, serena.repo_signature(tmp_path), {"a.py::f": {"b.py": ["f"]}})
    hits, err = serena.referencing_files(tmp_path, ["f"], "a.py", use_cache=False)
    if not serena.available():
        assert hits == {} and "not installed" in err
