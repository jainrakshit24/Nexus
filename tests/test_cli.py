"""AC6: the commands work end to end and fail loudly when they should."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus.cli import main  # noqa: E402


@pytest.fixture
def repo(tmp_path, monkeypatch):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "go.mod").write_text("module demo\n")
    return tmp_path / "repo"


def run(args, cwd=None):
    return main(args)


def test_init_then_status(repo, capsys):
    assert run(["init", str(repo), "--here"]) == 0
    out = capsys.readouterr().out
    assert "initialized" in out and "go test ./..." in out

    assert run(["--root", str(repo), "status"]) == 0
    assert "live      : 1" in capsys.readouterr().out


def test_remember_recall_roundtrip(repo, capsys):
    run(["init", str(repo), "--here"])
    assert run(["--root", str(repo), "remember", "Rate limiting lives in the gateway, not the app.",
                "--name", "rate-limiting", "--confidence", "verified",
                "--source", "gateway/limits.go:12"]) == 0
    assert run(["--root", str(repo), "recall", "rate", "limiting"]) == 0
    assert "rate-limiting" in capsys.readouterr().out


def test_recall_miss_exits_nonzero(repo, capsys):
    run(["init", str(repo), "--here"])
    assert run(["--root", str(repo), "recall", "quantum", "teleportation"]) == 1


def test_remember_with_secret_exits_3_and_names_pattern(repo, capsys):
    run(["init", str(repo), "--here"])
    code = run(["--root", str(repo), "remember", "prod key AKIA1234567890ABCDEF", "--name", "bad"])
    err = capsys.readouterr().err
    assert code == 3
    assert "aws-access-key-id" in err
    assert not (repo / ".nexus" / "project" / "bad.md").exists()


def test_verified_without_source_exits_2(repo, capsys):
    run(["init", str(repo), "--here"])
    assert run(["--root", str(repo), "remember", "x", "--name", "y", "--confidence", "verified"]) == 2
    assert "requires --source" in capsys.readouterr().err


def test_uninitialized_root_exits_4(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["status"]) == 4
    assert "run `nexus init`" in capsys.readouterr().err


def test_show_prints_supersede_history(repo, capsys):
    run(["init", str(repo), "--here"])
    base = ["--root", str(repo), "remember", "--name", "db", "--confidence", "verified"]
    run([*base[:3], "The database is MySQL.", *base[3:], "--source", "a.txt:1"])
    run([*base[:3], "The database is Postgres.", *base[3:], "--source", "b.txt:1"])
    capsys.readouterr()
    assert run(["--root", str(repo), "show", "db"]) == 0
    out = capsys.readouterr().out
    assert "MySQL" in out and "Postgres" in out


# ---------- Phase 2 commands ----------

def test_graph_command_without_a_graph_exits_6(repo, capsys):
    run(["init", str(repo), "--here"])
    assert run(["--root", str(repo), "graph"]) == 6
    assert "/graphify" in capsys.readouterr().err


def test_impact_without_a_graph_still_answers_from_text(repo, capsys):
    run(["init", str(repo), "--here"])
    (repo / "a.py").write_text("def alpha():\n    return 1\n")
    (repo / "b.py").write_text("from a import alpha\n\ndef beta():\n    return alpha()\n")
    assert run(["--root", str(repo), "impact", "a.py"]) == 0
    out = capsys.readouterr().out
    assert "b.py" in out and "text-only evidence" in out


def test_impact_json_is_machine_readable(repo, capsys):
    import json as _json
    run(["init", str(repo), "--here"])
    (repo / "a.py").write_text("def alpha():\n    return 1\n")
    (repo / "b.py").write_text("from a import alpha\n")
    capsys.readouterr()  # drop init's output so only the JSON remains
    assert run(["--root", str(repo), "impact", "a.py", "--json"]) == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["target"] == "a.py"
    assert {"blast_radius", "gear", "reason", "dependents"} <= set(payload)


def test_context_respects_the_budget_and_logs_the_three_numbers(repo, capsys):
    run(["init", str(repo), "--here"])
    (repo / "a.py").write_text("def alpha():\n    return 1\n" + "# filler\n" * 400)
    assert run(["--root", str(repo), "context", "refactor", "a.py", "--budget", "500"]) == 0
    cap = capsys.readouterr()
    from nexus import tokens as tk
    assert tk.count(cap.out) <= 500 * 1.4
    assert "estimated" in cap.err and "measured" in cap.err


def test_tokens_command_reports_host_usage_as_unavailable_when_absent(repo, capsys):
    run(["init", str(repo), "--here"])
    assert run(["--root", str(repo), "tokens"]) == 0
    out = capsys.readouterr().out
    assert "saved    (estimated)" in out
    assert "unavailable" in out
