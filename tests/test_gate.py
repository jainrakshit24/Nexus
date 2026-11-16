"""AC1, AC3, AC5: no pass without evidence; ADR before architecture; nothing destroyed silently."""
import subprocess
import sys

import pytest

from nexus import gate
from nexus.gate import TestRun, post_edit, pre_edit, revert_unintended
from nexus.record import Record
from nexus.store import Store


@pytest.fixture
def git_repo(graph_repo, monkeypatch, tmp_path):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    Store.init(graph_repo)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
        subprocess.run(["git", *args], cwd=graph_repo, capture_output=True)
    return graph_repo


# ---------- AC1: a pass requires captured output ----------

def test_a_passing_run_with_no_log_cannot_be_constructed():
    with pytest.raises(ValueError, match="without evidence"):
        TestRun(command="pytest", exit_code=0, log="")


def test_a_passing_run_with_only_whitespace_cannot_be_constructed():
    with pytest.raises(ValueError, match="without evidence"):
        TestRun(command="pytest", exit_code=0, log="   \n\t ")


def test_a_failing_run_with_no_log_is_allowed_because_it_claims_nothing():
    assert TestRun(command="pytest", exit_code=1, log="").passed is False


def test_not_run_is_neither_passed_nor_ran():
    t = TestRun.not_run("pytest", "no command detected")
    assert (t.ran, t.passed) == (False, False)
    assert "NOT RUN" in t.summary()


def test_a_silent_zero_exit_is_recorded_as_no_evidence(git_repo):
    run = gate.run_tests(git_repo, command="true")
    assert run.exit_code == 0
    assert "no evidence" in run.log
    assert run.passed is True and run.log.strip()   # the log exists, and says what it is


def test_a_real_failure_is_captured_and_quoted(git_repo):
    run = gate.run_tests(git_repo, command=f"{sys.executable} -c \"import sys; print('boom'); sys.exit(3)\"")
    assert run.ran and not run.passed and run.exit_code == 3
    assert "boom" in run.tail()


def test_post_edit_fails_and_quotes_the_failing_output(git_repo):
    (git_repo / "a.py").write_text("def alpha():\n    return 2   # changed\n")
    verdict = post_edit(git_repo, test_command=f"{sys.executable} -c \"import sys; print('ASSERT FAILED here'); sys.exit(1)\"")
    assert verdict.status == "FAIL"
    assert "ASSERT FAILED here" in verdict.render()


def test_skipping_tests_reports_unverified_not_pass(git_repo):
    (git_repo / "a.py").write_text("def alpha():\n    return 2\n")
    assert post_edit(git_repo, run=False).status == "UNVERIFIED"


# ---------- unintended changes and secrets ----------

def test_changes_outside_the_plan_are_flagged(git_repo):
    plan = pre_edit(git_repo, ["a.py"])
    gate.save_plan(git_repo, plan)
    (git_repo / "a.py").write_text("def alpha():\n    return 2\n")
    (git_repo / "d.py").write_text("def delta():\n    return 99\n")
    verdict = post_edit(git_repo, run=False)
    assert verdict.unintended == ["d.py"]


def test_a_credential_in_the_diff_blocks_everything(git_repo):
    (git_repo / "a.py").write_text('KEY = "AKIA1234567890ABCDEF"\n')
    verdict = post_edit(git_repo, run=False)
    assert verdict.status == "BLOCKED"
    assert any(s["pattern"] == "aws-access-key-id" for s in verdict.secrets)
    assert "1234567890ABCDEF" not in verdict.render()   # named, never reprinted


# ---------- AC3: ADR before an architectural change ----------

def test_a_schema_change_demands_an_adr_and_is_blocked_without_one(git_repo):
    (git_repo / "schema.sql").write_text("CREATE TABLE t (id int);\n")
    plan = pre_edit(git_repo, ["schema.sql"])
    assert plan.gear == "full"
    assert plan.adr_required and plan.adr_found is None
    assert plan.blocked
    assert "REQUIRED and MISSING" in plan.render()


def test_the_block_lifts_once_an_adr_names_the_target(git_repo):
    from nexus import adr
    (git_repo / "schema.sql").write_text("CREATE TABLE t (id int);\n")
    adr.create(git_repo, "Introduce the t table", affects=["schema.sql"],
               decision="Add table t.", index=False)
    plan = pre_edit(git_repo, ["schema.sql"])
    assert plan.adr_found and not plan.blocked


def test_an_unrelated_adr_does_not_satisfy_the_requirement(git_repo):
    from nexus import adr
    (git_repo / "schema.sql").write_text("CREATE TABLE t (id int);\n")
    adr.create(git_repo, "Something else entirely", affects=["unrelated.py"], index=False)
    assert pre_edit(git_repo, ["schema.sql"]).blocked


def test_an_ordinary_change_needs_no_adr(git_repo):
    plan = pre_edit(git_repo, ["a.py"])
    assert not plan.adr_required and not plan.blocked


# ---------- AC5: destructive actions require confirmation ----------

def test_revert_does_nothing_when_confirmation_is_declined(git_repo):
    (git_repo / "d.py").write_text("def delta():\n    return 99\n")
    asked = []
    reverted = revert_unintended(git_repo, ["d.py"], confirm=lambda f: asked.append(f) or False)
    assert reverted == []
    assert asked == [["d.py"]]
    assert "99" in (git_repo / "d.py").read_text()      # untouched


def test_revert_happens_only_on_an_explicit_yes(git_repo):
    (git_repo / "d.py").write_text("def delta():\n    return 99\n")
    reverted = revert_unintended(git_repo, ["d.py"], confirm=lambda _: True)
    assert reverted == ["d.py"]
    assert "99" not in (git_repo / "d.py").read_text()


def test_revert_with_nothing_to_do_never_asks(git_repo):
    def boom(_):
        raise AssertionError("must not prompt when there is nothing to revert")
    assert revert_unintended(git_repo, [], confirm=boom) == []


# ---------- plan content ----------

def test_the_plan_records_dependents_and_tests(git_repo):
    (git_repo / "test_a.py").write_text("from a import alpha\n\ndef test_alpha(): assert alpha()\n")
    plan = pre_edit(git_repo, ["a.py"])
    assert "b.py" in plan.dependents
    assert "test_a.py" in plan.tests_to_run


def test_the_plan_carries_relevant_memory(git_repo):
    Store(git_repo).write(Record(name="alpha-contract", type="project",
                                 body="alpha must keep returning an int.",
                                 confidence="verified", source="a.py:1"))
    assert any("alpha-contract" == m["name"] for m in pre_edit(git_repo, ["a.py"]).memories)


def test_a_plan_round_trips_through_disk(git_repo):
    saved = pre_edit(git_repo, ["a.py"])
    gate.save_plan(git_repo, saved)
    loaded = gate.load_latest_plan(git_repo)
    assert loaded and loaded.id == saved.id and loaded.targets == saved.targets


# ---------- diff scanning precision ----------

DIFF = """diff --git a/app.py b/app.py
index 111..222 100644
--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
-OLD = "AKIA0000000000000000"
+NEW = "AKIA1234567890ABCDEF"
diff --git a/tests/fixtures.py b/tests/fixtures.py
--- a/tests/fixtures.py
+++ b/tests/fixtures.py
@@ -0,0 +1 @@
+SAMPLE = "AKIA9999999999999999"
"""


def test_added_lines_are_separated_by_file():
    added = gate.added_lines_by_file(DIFF)
    assert set(added) == {"app.py", "tests/fixtures.py"}
    assert "AKIA1234567890ABCDEF" in added["app.py"]
    assert "AKIA0000000000000000" not in added["app.py"]   # the removed line


def test_a_credential_being_deleted_does_not_block(git_repo):
    (git_repo / "a.py").write_text('OLD = "AKIA0000000000000000"\n')
    subprocess.run(["git", "add", "-A"], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "add key"], cwd=git_repo, capture_output=True)
    (git_repo / "a.py").write_text("def alpha():\n    return 1\n")   # removes it
    assert post_edit(git_repo, run=False).secrets == []


def test_the_allowlist_moves_a_finding_out_of_blocking_without_hiding_it(git_repo):
    (git_repo / "tests").mkdir(exist_ok=True)
    (git_repo / "tests" / "fixtures.py").write_text('SAMPLE = "AKIA1234567890ABCDEF"\n')
    (git_repo / ".nexus").mkdir(exist_ok=True)
    (git_repo / ".nexus" / "secret-allowlist").write_text("aws-access-key-id tests/*\n")

    verdict = post_edit(git_repo, run=False)
    assert verdict.secrets == []
    assert [s["file"] for s in verdict.allowed_secrets] == ["tests/fixtures.py"]
    assert "allowed by `.nexus/secret-allowlist`" in verdict.render()
    assert verdict.status != "BLOCKED"


def test_the_allowlist_does_not_cover_other_paths(git_repo):
    (git_repo / ".nexus").mkdir(exist_ok=True)
    (git_repo / ".nexus" / "secret-allowlist").write_text("aws-access-key-id tests/*\n")
    (git_repo / "a.py").write_text('KEY = "AKIA1234567890ABCDEF"\n')
    assert post_edit(git_repo, run=False).status == "BLOCKED"


def test_the_allowlist_does_not_cover_other_patterns(git_repo):
    (git_repo / "tests").mkdir(exist_ok=True)
    (git_repo / ".nexus").mkdir(exist_ok=True)
    (git_repo / ".nexus" / "secret-allowlist").write_text("jwt tests/*\n")
    (git_repo / "tests" / "f.py").write_text('KEY = "AKIA1234567890ABCDEF"\n')
    assert post_edit(git_repo, run=False).status == "BLOCKED"


def test_allowlist_comments_and_blank_lines_are_ignored(git_repo):
    (git_repo / ".nexus").mkdir(exist_ok=True)
    (git_repo / ".nexus" / "secret-allowlist").write_text(
        "# a comment\n\naws-access-key-id tests/*   # trailing\n")
    assert gate.load_allowlist(git_repo) == [("aws-access-key-id", "tests/*")]
