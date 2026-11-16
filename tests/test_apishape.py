"""Public API shape, breaking-change rules, and the symbol helpers."""

from nexus import apishape, symbols
from nexus.apishape import compare, shape


def test_private_names_are_not_public_api():
    s = shape("def _hidden(): pass\ndef shown(): pass\nclass _Secret: pass\nclass Shown: pass\n")
    assert set(s) == {"shown", "Shown"}


def test_methods_are_captured_with_their_class():
    s = shape("class Thing:\n    def go(self, x): pass\n    def _priv(self): pass\n")
    assert "Thing.go" in s and "Thing._priv" not in s


def test_dunder_init_counts_because_callers_construct_it():
    assert "Thing.__init__" in shape("class Thing:\n    def __init__(self, x): pass\n")


def test_unparseable_source_yields_nothing_rather_than_guessing():
    assert shape("def broken(:\n") == {}


# ---------- what is and is not breaking ----------

def test_removing_a_function_is_breaking():
    [c] = compare(shape("def gone(): pass\n"), shape(""))
    assert c["change"] == "removed"


def test_adding_a_required_parameter_is_breaking():
    [c] = compare(shape("def f(a): pass\n"), shape("def f(a, b): pass\n"))
    assert c["change"] == "required parameter added" and "b" in c["why"]


def test_adding_an_optional_parameter_is_not_breaking():
    assert compare(shape("def f(a): pass\n"), shape("def f(a, b=1): pass\n")) == []


def test_renaming_a_parameter_is_breaking():
    [c] = compare(shape("def f(old): pass\n"), shape("def f(new): pass\n"))
    assert c["change"] == "parameter removed or renamed"


def test_removing_a_required_keyword_argument_is_breaking():
    [c] = compare(shape("def f(*, key): pass\n"), shape("def f(*, other): pass\n"))
    assert c["change"] == "keyword argument removed"


def test_adding_a_new_function_is_not_breaking():
    assert compare(shape("def a(): pass\n"), shape("def a(): pass\ndef b(): pass\n")) == []


def test_turning_a_function_into_a_class_is_breaking():
    [c] = compare(shape("def Thing(): pass\n"), shape("class Thing: pass\n"))
    assert c["change"] == "kind changed"


def test_accepting_kwargs_absorbs_a_removed_keyword():
    assert compare(shape("def f(*, key): pass\n"), shape("def f(**kw): pass\n")) == []


def test_a_renamed_method_is_breaking():
    before = shape("class T:\n    def go(self, x): pass\n")
    after = shape("class T:\n    def go(self, y): pass\n")
    assert compare(before, after)[0]["symbol"] == "T.go"


def test_rendering_shows_optional_parameters():
    assert "b=..." in shape("def f(a, b=1): pass\n")["f"].render()


# ---------- against git ----------

def test_a_new_file_has_nothing_to_break(tmp_path):
    (tmp_path / "new.py").write_text("def f(): pass\n")
    assert apishape.breaking_changes(tmp_path, "new.py") == []


def test_a_non_python_file_is_skipped(tmp_path):
    (tmp_path / "x.sql").write_text("SELECT 1;\n")
    assert apishape.breaking_changes(tmp_path, "x.sql") == []


# ---------- symbols ----------

def test_exported_names_skips_private_and_lowercase_constants(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("CONST = 1\nlower = 2\ndef pub(): pass\ndef _priv(): pass\nclass K: pass\n")
    assert symbols.exported_names(f) == {"CONST", "pub", "K"}


def test_generic_names_are_not_used_as_search_terms(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def read(): pass\ndef distinctive_thing(): pass\n")
    needles = symbols.needles_for(tmp_path, "m.py")
    assert "read" not in needles and "distinctive_thing" in needles


def test_references_respect_word_boundaries(tmp_path):
    (tmp_path / "a.py").write_text("def store_it(): pass\n")
    (tmp_path / "b.py").write_text("restore_it()\n")
    (tmp_path / "c.py").write_text("store_it()\n")
    hits = symbols.references(tmp_path, {"store_it"}, exclude={"a.py"})
    assert set(hits) == {"c.py"}


def test_outline_gives_shape_not_bodies(tmp_path):
    f = tmp_path / "m.py"
    f.write_text('"""Doc."""\ndef f(a, b):\n    x = 1\n    return x\n\nclass K:\n    pass\n')
    out = symbols.outline(f)
    assert "def f(a, b)" in out and "class K" in out
    assert "x = 1" not in out


def test_outline_of_an_unparseable_file_falls_back_to_declarations(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def broken(:\n    pass\nclass Later:\n")
    assert "class Later" in symbols.outline(f)


def test_test_files_are_recognised_by_several_conventions():
    for p in ("tests/test_a.py", "src/a_test.go", "spec/thing_spec.rb", "__tests__/x.js"):
        assert symbols.is_test_file(p), p
    assert not symbols.is_test_file("src/contest.py")
