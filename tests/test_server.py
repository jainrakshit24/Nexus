"""The MCP server, driven by NEXUS's own MCP client over a real subprocess.

AC1 lives here: the same `.nexus/` directory, reached through two
independently configured host launches, returns byte-identical answers.
"""
import json
import sys

import pytest

from nexus.mcpclient import MCPClient
from nexus.record import Record
from nexus.server import Server
from nexus.store import Store

PKG_ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[1])


@pytest.fixture
def served(graph_repo, monkeypatch, tmp_path):
    import nexus.store as store_mod
    monkeypatch.setattr(store_mod, "GLOBAL_DIR", tmp_path / "global")
    store = Store.init(graph_repo)
    store.write(Record(name="alpha-contract", type="project",
                       body="alpha() must keep returning an int.",
                       confidence="verified", source="a.py:1"))
    return graph_repo


def launch(root, env_extra=None, cwd=None):
    """Two hosts launch a stdio server differently; both must behave the same."""
    import os
    env = {**os.environ, "PYTHONPATH": PKG_ROOT, **(env_extra or {})}
    cmd = [sys.executable, "-m", "nexus.server", "--root", str(root)]
    return MCPClient(cmd, cwd=str(cwd or root), timeout=60, env=env)


# ---------- protocol ----------

def test_initialize_reports_tool_capability(served):
    with launch(served) as c:
        info = c.request("initialize", {"protocolVersion": "x", "capabilities": {},
                                        "clientInfo": {"name": "t", "version": "1"}})
    assert info["serverInfo"]["name"] == "nexus"
    assert "tools" in info["capabilities"]


def test_the_five_tools_are_advertised(served):
    with launch(served) as c:
        names = {t["name"] for t in c.tools()}
    assert names == {"nexus_recall", "nexus_remember", "nexus_impact",
                     "nexus_context", "nexus_gate"}


def test_every_tool_declares_a_schema_with_required_fields(served):
    with launch(served) as c:
        for t in c.tools():
            schema = t["inputSchema"]
            assert schema["type"] == "object"
            assert schema.get("required"), t["name"]
            assert t["description"].strip()


def test_an_unknown_tool_is_a_protocol_error_not_a_crash(served):
    from nexus.mcpclient import MCPError
    with launch(served) as c, pytest.raises(MCPError, match="unknown tool"):
        c.call("nexus_nope", {})


def test_notifications_get_no_reply():
    srv = Server(root=None)
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_malformed_input_does_not_kill_the_loop(tmp_path):
    import io
    out = io.StringIO()
    stdin = io.StringIO('not json\n\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n')
    assert Server(root=tmp_path).serve(stdin=stdin, stdout=out) == 0
    assert json.loads(out.getvalue().strip())["id"] == 1


# ---------- tools ----------

def test_recall_returns_the_stored_fact(served):
    with launch(served) as c:
        text = MCPClient.text_of(c.call("nexus_recall", {"query": "does alpha return an int"}))
    assert "alpha-contract" in text and "verified" in text


def test_recall_says_nothing_is_known_rather_than_inventing(served):
    with launch(served) as c:
        text = MCPClient.text_of(c.call("nexus_recall", {"query": "kubernetes ingress"}))
    assert "Nothing is known" in text


def test_remember_refuses_a_credential(served):
    with launch(served) as c:
        result = c.request("tools/call", {"name": "nexus_remember",
                                          "arguments": {"text": "key AKIA1234567890ABCDEF"}})
    assert result["isError"] is True
    assert "Refused" in MCPClient.text_of(result)


def test_remember_refuses_verified_without_a_source(served):
    with launch(served) as c:
        result = c.request("tools/call", {"name": "nexus_remember",
                                          "arguments": {"text": "x", "confidence": "verified"}})
    assert result["isError"] is True and "source" in MCPClient.text_of(result)


def test_impact_reaches_the_transitive_dependent(served):
    with launch(served) as c:
        text = MCPClient.text_of(c.call("nexus_impact", {"target": "a.py", "depth": 2}))
    assert "b.py" in text and "c.py" in text


def test_context_returns_the_pack_and_its_three_numbers(served):
    with launch(served) as c:
        text = MCPClient.text_of(c.call("nexus_context", {"task": "refactor a.py", "budget": 2000}))
    assert "NEXUS context" in text
    assert "actual" in text and "baseline" in text and "estimated" in text


def test_gate_pre_without_targets_is_an_error(served):
    with launch(served) as c:
        result = c.request("tools/call", {"name": "nexus_gate", "arguments": {"stage": "pre"}})
    assert result["isError"] is True


def test_gate_pre_blocks_a_schema_change_without_an_adr(served):
    (served / "schema.sql").write_text("CREATE TABLE t (id int);\n")
    with launch(served) as c:
        result = c.request("tools/call", {"name": "nexus_gate",
                                          "arguments": {"stage": "pre", "targets": ["schema.sql"]}})
    assert result["isError"] is True
    assert "BLOCKED" in MCPClient.text_of(result)


# ---------- AC1: host independence ----------

def test_two_differently_configured_hosts_get_identical_answers(served, tmp_path):
    """One host launches from the project root; the other from elsewhere with
    extra environment. Same .nexus/, so the answers must match exactly."""
    queries = [
        ("nexus_recall", {"query": "does alpha return an int"}),
        ("nexus_recall", {"query": "alpha contract"}),
        ("nexus_impact", {"target": "a.py", "depth": 2}),
    ]

    with launch(served) as host_a:
        answers_a = [MCPClient.text_of(host_a.call(n, a)) for n, a in queries]

    with launch(served, env_extra={"NEXUS_HOST": "codex-like"}, cwd=tmp_path) as host_b:
        answers_b = [MCPClient.text_of(host_b.call(n, a)) for n, a in queries]

    assert answers_a == answers_b
    assert all(a.strip() for a in answers_a)


def test_a_fact_written_through_one_host_is_visible_to_the_other(served, tmp_path):
    with launch(served) as host_a:
        host_a.call("nexus_remember", {"text": "The queue drains every 30 seconds.",
                                       "name": "queue-drain", "confidence": "verified",
                                       "source": "worker.py:12"})
    with launch(served, cwd=tmp_path) as host_b:
        text = MCPClient.text_of(host_b.call("nexus_recall", {"query": "how often the queue drains"}))
    assert "queue-drain" in text


# ---------- protocol version negotiation ----------

def test_the_server_echoes_the_version_the_client_asked_for(tmp_path):
    """A client that gets back a version it does not know simply disconnects.
    This is what made Claude Code report 'Failed to connect'."""
    srv = Server(root=tmp_path)
    for asked in ("2024-11-05", "2025-03-26", "2025-06-18"):
        reply = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": asked, "capabilities": {},
                                       "clientInfo": {"name": "t", "version": "1"}}})
        assert reply["result"]["protocolVersion"] == asked


def test_a_client_that_names_no_version_gets_the_server_default(tmp_path):
    from nexus.server import PROTOCOL_VERSION
    reply = Server(root=tmp_path).handle(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert reply["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_the_default_version_is_a_real_dated_revision():
    import re
    from nexus.server import PROTOCOL_VERSION
    assert re.fullmatch(r"20\d{2}-\d{2}-\d{2}", PROTOCOL_VERSION)
