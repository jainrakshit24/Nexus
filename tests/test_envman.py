"""AC4: .env.example lists every required key and not one real value."""
import pytest

from nexus import envman


def make_app(root):
    (root / "app").mkdir(exist_ok=True)
    (root / "app" / "db.py").write_text(
        'import os\nDSN = os.environ["DATABASE_URL"]\nPOOL = os.getenv("DB_POOL_SIZE", "5")\n')
    (root / "app" / "mail.js").write_text(
        'const key = process.env.SENDGRID_KEY;\nconst from = process.env["MAIL_FROM"];\n')
    (root / "docker-compose.yml").write_text(
        'services:\n  web:\n    environment:\n      REDIS_URL: ${REDIS_URL}\n')
    return root


def test_usage_is_found_across_languages(tmp_path):
    used = envman.scan_usage(make_app(tmp_path))
    assert {"DATABASE_URL", "DB_POOL_SIZE", "SENDGRID_KEY", "MAIL_FROM", "REDIS_URL"} <= set(used)
    assert "app/db.py" in used["DATABASE_URL"]


def test_example_contains_every_required_key(tmp_path):
    root = make_app(tmp_path)
    rep = envman.report(root, environ={})
    envman.write_example(root, rep)
    assert envman.keys_in_example(root) >= set(rep.used_in_code)


def test_example_contains_no_real_values(tmp_path):
    root = make_app(tmp_path)
    (root / ".env").write_text(
        "DATABASE_URL=postgres://admin:hunter2@db.internal:5432/app\n"
        "SENDGRID_KEY=SG.aaaaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n")
    rep = envman.report(root, environ={})
    text = envman.write_example(root, rep).read_text()

    assert "hunter2" not in text and "SG.aaaa" not in text
    assert "postgres://" not in text
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            assert line.split("=", 1)[1] == envman.PLACEHOLDER, line

    from nexus import scrub
    assert [f for f in scrub.scan(text) if f.severity == "secret"] == []


def test_declared_keys_are_read_without_their_values(tmp_path):
    root = make_app(tmp_path)
    (root / ".env").write_text("DATABASE_URL=postgres://u:p@h/db\nEXTRA_FLAG=1\n")
    assert envman.keys_in_env_files(root) == {"DATABASE_URL", "EXTRA_FLAG"}


def test_a_variable_the_code_needs_but_nobody_declared_is_surfaced(tmp_path):
    root = make_app(tmp_path)
    (root / ".env").write_text("DATABASE_URL=x\n")
    assert "SENDGRID_KEY" in envman.report(root, environ={}).undeclared


def test_a_declared_but_unused_variable_is_surfaced(tmp_path):
    root = make_app(tmp_path)
    (root / ".env").write_text("OLD_FEATURE_FLAG=1\n")
    assert "OLD_FEATURE_FLAG" in envman.report(root, environ={}).unused


def test_runtime_presence_is_checked_against_the_given_environment(tmp_path):
    root = make_app(tmp_path)
    rep = envman.report(root, environ={"DATABASE_URL": "x"})
    assert "DATABASE_URL" not in rep.missing_at_runtime
    assert "SENDGRID_KEY" in rep.missing_at_runtime


def test_env_files_are_never_scanned_for_usage(tmp_path):
    root = make_app(tmp_path)
    (root / ".env").write_text("SOMETHING_ONLY_IN_ENV=1\n")
    assert "SOMETHING_ONLY_IN_ENV" not in envman.scan_usage(root)


def test_an_unprotected_env_file_is_detectable(tmp_path):
    root = make_app(tmp_path)
    assert envman.gitignore_protects_env(root) is False
    (root / ".gitignore").write_text("__pycache__/\n.env\n")
    assert envman.gitignore_protects_env(root) is True


def _proj(tmp_path):
    (tmp_path / "app.py").write_text(
        'import os\nos.environ["DATABASE_URL"]\nos.getenv("API_KEY")\n', encoding="utf-8")
    (tmp_path / ".env.production").write_text("DATABASE_URL=x\nAPI_KEY=y\n", encoding="utf-8")
    (tmp_path / ".env.development").write_text("API_KEY=y\n", encoding="utf-8")
    return tmp_path


def test_a_variable_declared_only_for_prod_is_not_declared_for_dev(tmp_path):
    """Unioning every .env* file gives dev a clean bill of health for a variable
    that would fail at boot. That false pass is the whole point of the split."""
    rep = envman.report(_proj(tmp_path), environ={})
    assert rep.environment == "dev"
    assert "DATABASE_URL" in rep.missing_for_this_environment
    assert "DATABASE_URL" not in rep.declared


def test_the_same_project_is_clean_for_prod(tmp_path):
    rep = envman.report(_proj(tmp_path), environ={}, environment="prod")
    assert rep.missing_for_this_environment == set()
    assert {"DATABASE_URL", "API_KEY"} <= rep.declared


def test_each_name_is_reported_under_exactly_one_heading(tmp_path):
    rep = envman.report(_proj(tmp_path), environ={})
    assert not (rep.undeclared & rep.missing_for_this_environment)


def test_an_unknown_environment_is_refused_rather_than_silently_defaulted(tmp_path):
    with pytest.raises(ValueError):
        envman.report(tmp_path, environ={}, environment="preprod")


def test_write_example_is_the_only_file_this_module_writes(tmp_path):
    """`NEXUS never writes to production config` has to be a property, not a promise."""
    import inspect
    src = inspect.getsource(envman)
    writers = [ln.strip() for ln in src.splitlines()
               if "write_text(" in ln and not ln.strip().startswith("#")]
    assert writers, "expected at least one writer to exist"
    assert len(writers) == 1, f"a second writer appeared in envman: {writers}"
    rep = envman.report(_proj(tmp_path), environ={})
    assert envman.write_example(tmp_path, rep).name == ".env.example"
