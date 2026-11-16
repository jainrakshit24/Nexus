"""Static checks, evidence, migrations and secret stores."""
import sys

import pytest

from nexus import checks, evidence, migrations, secrets


# ---------- the shared honesty invariant ----------

def test_a_passing_run_with_no_output_cannot_exist():
    with pytest.raises(ValueError, match="without evidence"):
        evidence.Run(command="ruff", exit_code=0, log="", name="lint")


def test_the_error_names_the_check_that_tried_to_lie():
    with pytest.raises(ValueError, match="passing lint"):
        evidence.Run(command="ruff", exit_code=0, log="  ", name="lint")


def test_not_run_is_a_third_state_distinct_from_pass_and_fail():
    r = evidence.Run.not_run("mypy", "no type checker configured", "types")
    assert (r.ran, r.passed, r.status) == (False, False, "not-run")
    assert "NOT RUN" in r.summary()


def test_a_silent_zero_exit_is_recorded_as_no_evidence(tmp_path):
    r = evidence.execute("probe", ["true"], tmp_path)
    assert r.exit_code == 0 and "no evidence" in r.log


def test_a_failure_captures_output(tmp_path):
    r = evidence.execute("probe", [sys.executable, "-c", "import sys;print('bad');sys.exit(2)"], tmp_path)
    assert r.status == "fail" and r.exit_code == 2 and "bad" in r.tail()


def test_a_missing_binary_is_not_run_rather_than_failed(tmp_path):
    r = evidence.execute("probe", ["definitely-not-a-real-binary-xyz"], tmp_path)
    assert not r.ran and "could not start" in r.log


# ---------- detection ----------

def test_nothing_configured_is_reported_as_such_not_as_a_pass(tmp_path):
    results = {r.name: r for r in checks.run(tmp_path)}
    for kind in ("lint", "types"):
        assert results[kind].status == "not-run"
        assert "no " + kind + " tool is configured" in results[kind].log
        assert results[kind].passed is False


def test_ruff_is_detected_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    assert checks.plan(tmp_path)["lint"].tool == "ruff"


def test_mypy_is_detected_from_its_own_file(tmp_path):
    (tmp_path / "mypy.ini").write_text("[mypy]\n")
    assert checks.plan(tmp_path)["types"].tool == "mypy"


def test_eslint_and_tsc_are_detected_for_node(tmp_path):
    (tmp_path / ".eslintrc.json").write_text("{}")
    (tmp_path / "tsconfig.json").write_text("{}")
    chosen = checks.plan(tmp_path)
    assert (chosen["lint"].tool, chosen["types"].tool) == ("eslint", "tsc")


def test_the_first_configured_linter_wins(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    (tmp_path / ".flake8").write_text("[flake8]\n")
    assert checks.plan(tmp_path)["lint"].tool == "ruff"


def test_configured_but_missing_is_a_broken_setup_not_a_pass(tmp_path):
    (tmp_path / "mypy.ini").write_text("[mypy]\n")
    result = {r.name: r for r in checks.run(tmp_path)}["types"]
    if result.ran:
        pytest.skip("mypy is installed on this machine")
    assert "not installed" in result.log and "not a pass" in result.log
    assert result.passed is False


def test_nexus_never_installs_a_tool():
    import inspect
    src = inspect.getsource(checks)
    for forbidden in ("pip install", "npm install", "uv tool install", "cargo install"):
        assert forbidden not in src


# ---------- advisory ids ----------

@pytest.mark.parametrize("log,expected", [
    ("urllib3 2.0.0 GHSA-abcd-1234-wxyz", ["GHSA-ABCD-1234-WXYZ"]),
    ("affected by CVE-2024-12345", ["CVE-2024-12345"]),
    ("PYSEC-2023-45 and RUSTSEC-2021-0078", ["PYSEC-2023-45", "RUSTSEC-2021-0078"]),
    ("nothing here", []),
])
def test_advisory_ids_are_extracted(log, expected):
    assert checks.advisories(log) == expected


def test_advisory_ids_are_deduplicated():
    assert checks.advisories("CVE-2024-1111 again CVE-2024-1111") == ["CVE-2024-1111"]


# ---------- migrations ----------

def test_destructive_sql_is_flagged(tmp_path):
    d = tmp_path / "db" / "migrations"
    d.mkdir(parents=True)
    (d / "0001_drop.sql").write_text("ALTER TABLE orders DROP COLUMN legacy;\n")
    report = migrations.validate(tmp_path)
    assert [x["rule"] for x in report["destructive"]] == ["drop-column"]


def test_a_branched_history_is_flagged(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0002_a.py").write_text("revision = 'b'\ndown_revision = 'a'\n")
    (d / "0003_b.py").write_text("revision = 'c'\ndown_revision = 'a'\n")
    assert any("branched history" in h for h in migrations.validate(tmp_path)["history"])


def test_duplicate_migration_numbers_are_flagged(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0002_one.py").write_text("x = 1\n")
    (d / "0002_two.py").write_text("x = 2\n")
    assert any("duplicate migration number" in h for h in migrations.validate(tmp_path)["history"])


def test_a_safe_migration_raises_nothing(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0001_add.sql").write_text("ALTER TABLE t ADD COLUMN note text DEFAULT '';\n")
    report = migrations.validate(tmp_path)
    assert report["destructive"] == [] and report["history"] == []


def test_not_null_without_a_default_is_flagged(tmp_path):
    d = tmp_path / "migrations"
    d.mkdir()
    (d / "0001.sql").write_text("ALTER TABLE t ADD COLUMN x integer NOT NULL;\n")
    assert [x["rule"] for x in migrations.validate(tmp_path)["destructive"]] == \
        ["not-null-without-default"]


def test_a_project_with_no_migrations_reports_nothing(tmp_path):
    assert migrations.validate(tmp_path) == {"checked": [], "destructive": [], "history": []}


# ---------- secret stores ----------

def test_backends_are_reported_truthfully():
    names = [b.name for b in secrets.backends()]
    assert names == ["secret-tool", "pass", "security"]
    for b in secrets.backends():
        assert isinstance(b.available, bool)


def test_a_missing_secret_returns_none_and_a_reason():
    value, source = secrets.get("NEXUS_DEFINITELY_ABSENT_KEY")
    assert value is None and source


def test_nothing_in_the_secrets_module_writes_a_value():
    """A secret must leave no trace. Checked against the AST, not the prose:
    a docstring promising not to cache is not evidence of anything."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(secrets))
    writers = {"write_text", "write_bytes", "write", "writelines", "dump", "dumps",
               "open", "mkdir", "touch"}
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name in writers:
            offenders.append(name)
    assert offenders == [], f"secrets module calls {offenders}"
