"""AC2: an isolated change must not summon specialists."""
from nexus.roles import needs_adr, route


def names(*a, **kw):
    return [r.name for r in route(*a, **kw)]


def test_one_file_no_dependents_gets_the_developer_only(graph_repo):
    assert names(["utils/format.py"], 0, True, "light") == ["developer"]


def test_a_dependent_pulls_in_qa(graph_repo):
    assert "qa" in names(["utils/format.py"], 2, True, "full")


def test_absent_tests_strengthen_the_qa_case_rather_than_skipping_it():
    qa = [r for r in route(["mod.py"], 3, False, "full") if r.name == "qa"]
    assert qa and "nothing covers them" in qa[0].why


def test_auth_paths_always_reach_security():
    assert "security" in names(["app/auth/login.py"], 0, False, "light")


def test_ci_config_always_reaches_devops():
    assert "devops" in names([".github/workflows/ci.yml"], 0, False, "light")


def test_migrations_reach_architect_and_data():
    got = names(["db/migrations/0003_add_column.py"], 1, True, "full")
    assert {"architect", "data"} <= set(got)


def test_a_wide_change_reaches_the_architect_on_blast_radius_alone():
    assert "architect" in names(["service.py"], 9, True, "full")


def test_roles_are_unique_and_ordered():
    got = names(["app/auth/schema.sql"], 7, True, "full")
    assert len(got) == len(set(got))
    assert got[0] == "developer"


def test_adr_is_required_for_architectural_surfaces():
    assert needs_adr(["db/schema.sql"])[0] is True
    assert needs_adr(["api/routes.py"])[0] is True
    assert needs_adr(["utils/format.py"])[0] is False


def test_adr_is_required_when_several_modules_appear_at_once():
    required, why = needs_adr(["a.py"], new_files=["a.py", "b.py", "c.py"])
    assert required and "3 new modules" in why
