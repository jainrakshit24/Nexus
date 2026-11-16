"""The MCP stdio client, against a fake server. No network, no uvx."""
import json
import sys
import textwrap

import pytest

from nexus.mcpclient import MCPClient, MCPError

FAKE_SERVER = textwrap.dedent('''
    import json, sys
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            continue                      # a notification: no reply
        if method == "initialize":
            out = {"protocolVersion": "x", "serverInfo": {"name": "fake"}}
        elif method == "tools/list":
            out = {"tools": [{"name": "echo", "inputSchema": {}}]}
        elif method == "tools/call":
            args = msg["params"]["arguments"]
            if args.get("boom"):
                out = {"isError": True, "content": [{"type": "text", "text": "nope"}]}
            else:
                out = {"content": [{"type": "text", "text": args.get("text", "")}]}
        else:
            print(json.dumps({"jsonrpc": "2.0", "id": mid,
                              "error": {"code": -32601, "message": "no such method"}}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": out}), flush=True)
''')


@pytest.fixture
def server_cmd(tmp_path):
    p = tmp_path / "fake_server.py"
    p.write_text(FAKE_SERVER)
    return [sys.executable, str(p)]


def test_initialize_list_and_call(server_cmd):
    with MCPClient(server_cmd, timeout=10) as c:
        assert [t["name"] for t in c.tools()] == ["echo"]
        assert MCPClient.text_of(c.call("echo", {"text": "hello"})) == "hello"


def test_server_error_result_raises(server_cmd):
    with MCPClient(server_cmd, timeout=10) as c:
        with pytest.raises(MCPError):
            c.call("echo", {"boom": True})


def test_unknown_method_raises_with_the_server_message(server_cmd):
    with MCPClient(server_cmd, timeout=10) as c:
        with pytest.raises(MCPError, match="no such method"):
            c.request("does/not/exist")


def test_ids_are_matched_so_responses_do_not_cross(server_cmd):
    with MCPClient(server_cmd, timeout=10) as c:
        assert MCPClient.text_of(c.call("echo", {"text": "one"})) == "one"
        assert MCPClient.text_of(c.call("echo", {"text": "two"})) == "two"


def test_calling_before_start_is_an_error(server_cmd):
    with pytest.raises(MCPError, match="not running"):
        MCPClient(server_cmd).request("initialize")


def test_text_of_handles_non_dict_results():
    assert MCPClient.text_of("plain") == "plain"
    assert MCPClient.text_of({"content": []}) == ""


def test_session_regex_matches_serenas_wording():
    from nexus.serena import SESSION_RE
    m = SESSION_RE.search("Your Serena session id is `a7ae65ba`. Pass it as the `session` parameter.")
    assert m and m.group(1) == "a7ae65ba"


def test_serena_reports_absence_instead_of_failing(monkeypatch, tmp_path):
    import nexus.serena as s
    monkeypatch.setattr(s.shutil, "which", lambda _: None)
    hits, err = s.referencing_files(tmp_path, ["Thing"], "a.py")
    assert hits == {} and "not installed" in err
