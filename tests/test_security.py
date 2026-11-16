"""Repository contents must never become shell input.

A directory name, a config value or a filename is attacker-controlled on any
repo you did not write. These tests pin the boundary that was missing until
the 2026-11-16 audit, when `pytest skills/a$(id -u)/tests` was shown to reach
`subprocess.run(..., shell=True)`.
"""

import pytest

from nexus import discover, evidence
from nexus.gate import run_tests

HOSTILE = [
    "a$(id -u)",
    "b;touch pwned",
    "c`id`",
    "d|tee pwned",
    "e&&touch pwned",
    "f'quote",
]


@pytest.mark.parametrize("name", HOSTILE)
def test_a_hostile_directory_never_reaches_the_test_command(tmp_path, name):
    nested = tmp_path / "pkg" / name / "tests"
    nested.mkdir(parents=True)
    (nested / "test_x.py").write_text("def test_x():\n    assert True\n")
    assert discover.profile(tmp_path)["test_command"] == ""


def test_a_well_behaved_nested_path_is_still_found(tmp_path):
    nested = tmp_path / "pkg" / "sub-module_1" / "tests"
    nested.mkdir(parents=True)
    (nested / "test_x.py").write_text("def test_x():\n    assert True\n")
    assert discover.profile(tmp_path)["test_command"] == "pytest pkg/sub-module_1/tests"


def test_execute_does_not_interpret_shell_metacharacters(tmp_path):
    marker = tmp_path / "pwned"
    run = evidence.execute("probe", f"echo hello; touch {marker}", tmp_path)
    assert not marker.exists(), "a shell interpreted the command"
    # `echo` received the rest as literal arguments
    assert "touch" in run.log


def test_execute_accepts_an_argv_list(tmp_path):
    run = evidence.execute("probe", ["echo", "literal;text"], tmp_path)
    assert run.passed and "literal;text" in run.log


def test_a_detected_command_is_never_run_through_a_shell(tmp_path, monkeypatch):
    """Even asking for shell mode must not apply it to a discovered command."""
    marker = tmp_path / "pwned"
    monkeypatch.setattr(discover, "profile",
                        lambda _root: {"test_command": f"echo x; touch {marker}"})
    run_tests(tmp_path, command=None, shell=True)
    assert not marker.exists()


def test_a_human_typed_command_may_opt_into_a_shell(tmp_path):
    marker = tmp_path / "deliberate"
    run_tests(tmp_path, command=f"echo x && touch {marker}", shell=True)
    assert marker.exists(), "an explicit --shell command should reach a shell"


def test_without_opting_in_a_human_command_is_argv_split(tmp_path):
    marker = tmp_path / "accidental"
    run_tests(tmp_path, command=f"echo x && touch {marker}")
    assert not marker.exists()


def test_static_checks_never_reach_a_shell(tmp_path):
    """Checker commands are fixed literals, but the path must stay closed."""
    import inspect
    from nexus import checks
    assert "shell=True" not in inspect.getsource(checks)


def test_no_module_calls_subprocess_with_an_implicit_shell():
    import inspect
    import nexus.checks, nexus.dashboard, nexus.discover, nexus.gate, nexus.graph  # noqa
    import nexus.apishape, nexus.evidence  # noqa
    offenders = []
    for mod in (nexus.checks, nexus.dashboard, nexus.discover, nexus.gate,
                nexus.graph, nexus.apishape):
        src = inspect.getsource(mod)
        if "shell=True" in src:
            offenders.append(mod.__name__)
    assert offenders == [], f"{offenders} pass shell=True"


def test_the_only_shell_switch_is_a_parameter_with_a_safe_default():
    import inspect
    sig = inspect.signature(evidence.execute)
    assert sig.parameters["shell"].default is False
