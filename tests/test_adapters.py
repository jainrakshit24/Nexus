"""Host adapters, hooks, and the dashboard's separation from the agent."""
import json
from pathlib import Path

import pytest

from nexus import adapters, dashboard, hooks
from nexus.record import Record
from nexus.store import Store


# ---------- adapters ----------

MCP_HOSTS = ("claude-code", "codex", "cursor", "vscode")


def test_every_mcp_host_produces_a_launchable_server_command(tmp_path):
    for host in MCP_HOSTS:
        arts = adapters.generate(host, tmp_path)
        blob = "\n".join(a.content for a in arts)
        assert "nexus.server" in blob, host
        assert str(tmp_path.resolve()) in blob, host


def test_git_hooks_is_a_commit_gate_not_an_mcp_client(tmp_path):
    arts = adapters.generate("git-hooks", tmp_path)
    assert [a.path for a in arts] == [".git/hooks/pre-commit"]
    assert "nexus.server" not in arts[0].content
    assert "hook pre-commit" in arts[0].content
    assert arts[0].executable


def test_the_commit_gate_documents_its_bypass(tmp_path):
    script = adapters.generate("git-hooks", tmp_path)[0].content
    assert "NEXUS_SKIP_GATE" in script
    assert script.startswith("#!/bin/sh")


def test_the_commit_gate_is_written_executable(tmp_path):
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    adapters.write(tmp_path, adapters.generate("git-hooks", tmp_path))
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    assert hook.exists() and hook.stat().st_mode & 0o111


def test_mcp_json_files_are_valid_json(tmp_path):
    for host in ("claude-code", "cursor", "vscode"):
        for a in adapters.generate(host, tmp_path):
            if a.path.endswith(".json"):
                json.loads(a.content)


def test_claude_code_hooks_point_at_the_nexus_handler(tmp_path):
    settings = next(a for a in adapters.claude_code(tmp_path) if a.path.endswith("settings.json"))
    cfg = json.loads(settings.content)
    commands = [h["command"] for group in cfg["hooks"].values()
                for entry in group for h in entry["hooks"]]
    assert any("hook session-start" in c for c in commands)
    assert any("hook post-tool" in c for c in commands)


def test_hooks_can_be_declined(tmp_path):
    assert not any(a.path.endswith("settings.json")
                   for a in adapters.claude_code(tmp_path, hooks=False))


def test_codex_gets_agents_md_and_a_toml_block(tmp_path):
    paths = [a.path for a in adapters.codex(tmp_path)]
    assert paths == ["AGENTS.md", "~/.codex/config.toml"]
    assert "[mcp_servers.nexus]" in adapters.codex(tmp_path)[1].content


def test_a_global_config_is_never_written_only_printed(tmp_path):
    results = dict(adapters.write(tmp_path, adapters.codex(tmp_path)))
    assert "skipped" in results["~/.codex/config.toml"]
    assert not (tmp_path / "~").exists()


def test_existing_files_are_not_clobbered_without_force(tmp_path):
    (tmp_path / ".mcp.json").write_text('{"mine": true}')
    arts = adapters.claude_code(tmp_path)
    assert "not overwritten" in dict(adapters.write(tmp_path, arts))[".mcp.json"]
    assert json.loads((tmp_path / ".mcp.json").read_text()) == {"mine": True}
    adapters.write(tmp_path, arts, force=True)
    assert "mcpServers" in (tmp_path / ".mcp.json").read_text()


def test_an_unknown_host_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown host"):
        adapters.generate("emacs", tmp_path)


def test_the_guidance_tells_the_agent_to_check_before_editing():
    g = adapters.GUIDANCE
    assert "nexus_impact" in g and "before editing" in g
    assert "never store a credential" in g


# ---------- hooks ----------

@pytest.fixture
def hooked(graph_repo, monkeypatch, tmp_path):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    store = Store.init(graph_repo)
    store.write(Record(name="project-overview", type="project",
                       body="Demo package.", confidence="observed", source="fixture"))
    return graph_repo


def test_session_start_is_short_and_states_graph_health(hooked):
    text = hooks.session_start({}, str(hooked))
    assert "NEXUS memory:" in text and "Knowledge graph:" in text
    assert len(text.splitlines()) <= 8          # it costs context; keep it small


def test_session_start_outside_a_project_says_nothing(tmp_path):
    assert hooks.session_start({}, str(tmp_path / "nowhere")) == ""


def test_post_tool_records_a_real_test_run(hooked):
    hooks.post_tool({"tool_name": "Bash",
                     "tool_input": {"command": "python3 -m pytest tests -q"},
                     "tool_response": {"exit_code": 0, "stdout": "12 passed"}}, str(hooked))
    hits = Store(hooked).recall("pytest test run", type_="episodic")
    assert hits and hits[0]["confidence"] == "verified"


def test_post_tool_records_a_failure_distinctly(hooked):
    hooks.post_tool({"tool_name": "Bash",
                     "tool_input": {"command": "pytest"},
                     "tool_response": {"exit_code": 1, "stdout": "1 failed"}}, str(hooked))
    assert any("fail" in h["name"] for h in Store(hooked).recall("pytest", type_="episodic"))


def test_post_tool_ignores_commands_that_are_not_tests(hooked):
    hooks.post_tool({"tool_name": "Bash", "tool_input": {"command": "ls -la"},
                     "tool_response": {"exit_code": 0}}, str(hooked))
    assert Store(hooked).stats()["by_type"].get("episodic", 0) == 0


def test_post_tool_records_nothing_when_the_host_reports_no_exit_code(hooked):
    """Without an exit code we learned nothing, so nothing becomes a fact."""
    hooks.post_tool({"tool_name": "Bash", "tool_input": {"command": "pytest"},
                     "tool_response": {"stdout": "looked fine"}}, str(hooked))
    assert Store(hooked).stats()["by_type"].get("episodic", 0) == 0


def test_a_broken_hook_never_fails_the_session(hooked):
    import io
    assert hooks.run("session-start", stream=io.StringIO("}{ not json"), root_hint=str(hooked)) == 0
    assert hooks.run("no-such-hook", stream=io.StringIO("{}")) == 0


# ---------- dashboard: AC2 ----------

def test_the_dashboard_is_unreachable_from_the_agent_facing_server():
    """Zero tokens is a structural property, not a promise: the server module
    must not import the dashboard, and no tool may return its content."""
    source = Path(__import__("nexus.server", fromlist=["x"]).__file__).read_text()
    assert "dashboard" not in source

    from nexus import server
    assert all("dashboard" not in (h.__doc__ or "") for h in server.HANDLERS.values())
    assert not any("dashboard" in json.dumps(t).lower() for t in server.TOOLS)


def test_state_reports_memory_graph_task_and_three_token_numbers(hooked):
    s = dashboard.state(hooked)
    assert s["memory"]["live"] >= 1
    assert s["graph"]["available"] is True and "detail" in s["graph"]
    assert set(s["task"]) >= {"plan_id", "targets", "gear", "roles"}
    assert {"actual_measured", "baseline_measured", "saved_estimated"} <= set(s["tokens"])


def test_state_survives_a_project_with_no_graph(tmp_path, monkeypatch):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    Store.init(tmp_path)
    s = dashboard.state(tmp_path)
    assert s["graph"]["available"] is False and s["graph"]["detail"]


def test_the_compact_line_fits_a_status_bar(hooked):
    line = dashboard.compact_line(dashboard.state(hooked))
    assert line.startswith("nexus ·") and "\n" not in line and len(line) < 120


def test_the_static_page_embeds_the_state_and_needs_no_server(hooked, tmp_path):
    out = dashboard.render_static(hooked, tmp_path / "snap.html")
    html = out.read_text()
    assert "setInterval" not in html
    assert '"live"' in html and "saved_estimated" in html


def test_the_page_labels_saved_as_an_estimate():
    assert "estimate" in dashboard.PAGE
    assert "counterfactual" in dashboard.PAGE
