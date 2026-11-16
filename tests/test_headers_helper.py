"""`sheaf headers`, the headersHelper of the door's MCP entry (SPEC 9.14, 13): Claude Code runs it when it connects the
door and sends what it prints as request headers, so a door write names the session, the machine and the Remote Control
link as a send does. `sheaf headers --check NAME` says whether an MCP entry carries it, for the mod. Run in a temp home
and a temp Claude config folder; the keyring is out of reach (premortem R7), because the helper has no business with a
token and its output holds none."""
import json

import pytest

from sheafmd import connect, send
from sheafmd.cli import main

SESSION = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11"
LINK = "https://claude.ai/code/session_01ABC"
ORIGIN = "https://chat.example.com"


@pytest.fixture(autouse=True)
def no_real_keyring(monkeypatch):
    def refuse():
        raise AssertionError("a test asked for the real keyring (R7): the helper never reads a token")
    monkeypatch.setattr(connect, "system_store", refuse)
    monkeypatch.setattr(send, "machine", lambda: "laptop-bea")


@pytest.fixture
def registry(tmp_path, monkeypatch):
    cfg = tmp_path / "claude"
    (cfg / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)

    def record(**more):
        (cfg / "sessions" / "1.json").write_text(json.dumps({"pid": 1, "sessionId": SESSION, **more}), encoding="utf-8")
    return record


def run(capsys, *argv):
    code = main(["headers", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_it_prints_the_session_the_machine_and_the_remote_control_link_as_one_json_object(registry, capsys):
    registry(remoteControlUrl=LINK)
    code, out, err = run(capsys)
    assert code == 0 and err == ""
    assert json.loads(out) == {"X-Sheaf-Session": SESSION, "X-Sheaf-Host": "laptop-bea", "X-Sheaf-Link": LINK}


def test_it_prints_no_link_when_the_session_has_none_or_it_is_no_web_address(registry, capsys):
    registry()
    assert json.loads(run(capsys)[1]) == {"X-Sheaf-Session": SESSION, "X-Sheaf-Host": "laptop-bea"}
    registry(remoteControlUrl="javascript:alert(1)")
    assert "X-Sheaf-Link" not in json.loads(run(capsys)[1])


def test_with_no_session_it_still_prints_the_machine_and_exits_0(monkeypatch, capsys):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    code, out, _ = run(capsys)
    assert code == 0 and json.loads(out) == {"X-Sheaf-Host": "laptop-bea"}


def test_its_output_never_holds_a_token(registry, capsys):
    registry(remoteControlUrl=LINK)
    out = run(capsys)[1]
    assert not any(w in out.lower() for w in ("authorization", "bearer", "sheaf_mcp_", "token"))


def entry(helper=None):
    e = {"type": "http", "url": ORIGIN + connect.DOOR_PATH, "headers": {"Authorization": "Bearer t"}}
    if helper is not None:
        e["headersHelper"] = helper
    return e


@pytest.fixture
def claude_json(tmp_path, monkeypatch):
    path = tmp_path / ".claude.json"
    monkeypatch.setattr(connect, "claude_json", lambda: path)
    return lambda servers: path.write_text(json.dumps({"mcpServers": servers}))


def test_check_says_yes_only_for_a_door_entry_that_carries_the_helper(claude_json, capsys):
    name = connect.entry_name(ORIGIN)
    claude_json({name: entry("sheaf headers"), "sheaf-old.example.com": entry(), "other": {"type": "http", "url": "https://x/mcp", "headersHelper": "x"}})
    for given in (name, "sheaf-chat_example_com"):          # the entry's key, and as a tool name writes it
        assert run(capsys, "--check", given) == (0, "", "")
    assert run(capsys, "--check", "sheaf-old.example.com")[0] == 1      # an entry made before the helper
    assert run(capsys, "--check", "sheaf-old_example_com")[0] == 1
    assert run(capsys, "--check", "other")[0] == 1                      # not a Sheaf door
    assert run(capsys, "--check", "sheaf-nothing")[0] == 1


def test_check_says_no_when_claude_json_is_missing_or_unreadable(tmp_path, monkeypatch, capsys):
    path = tmp_path / ".claude.json"
    monkeypatch.setattr(connect, "claude_json", lambda: path)
    assert run(capsys, "--check", "sheaf-chat.example.com")[0] == 1
    path.write_text("{not json")
    assert run(capsys, "--check", "sheaf-chat.example.com")[0] == 1
