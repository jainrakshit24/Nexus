"""AC1: discovery reports what the repo actually is."""
import json

from nexus import discover


def test_node_repo_with_test_script(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
    (tmp_path / "pnpm-lock.yaml").write_text("")
    p = discover.profile(tmp_path)
    assert p["stack"] == "node"
    assert p["test_command"] == "pnpm test"


def test_node_repo_without_test_script_claims_nothing(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))
    assert discover.profile(tmp_path)["test_command"] == ""


def test_python_repo_root_tests(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("def test_a(): pass\n")
    p = discover.profile(tmp_path)
    assert p["stack"] == "python"
    assert p["test_command"] == "pytest"


def test_nested_tests_are_found(tmp_path):
    """Monorepo shape: no root marker, tests two levels down."""
    deep = tmp_path / "skills" / "thing" / "tests"
    deep.mkdir(parents=True)
    (deep / "test_x.py").write_text("def test_x(): pass\n")
    (tmp_path / "skills" / "thing" / "run.py").write_text("print(1)\n")
    p = discover.profile(tmp_path)
    assert p["stack"].startswith("python")
    assert p["test_command"] == "pytest skills/thing/tests"


def test_go_repo(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    p = discover.profile(tmp_path)
    assert (p["stack"], p["test_command"]) == ("go", "go test ./...")


def test_census_skips_vendor_dirs(tmp_path):
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "a.js").write_text("x")
    (tmp_path / "app.py").write_text("x")
    assert discover.profile(tmp_path)["file_count"] == 1


def test_markdown_states_its_own_confidence(tmp_path):
    (tmp_path / "go.mod").write_text("module x\n")
    md = discover.to_markdown(discover.profile(tmp_path))
    assert "observed" in md and "not verified by running anything" in md
