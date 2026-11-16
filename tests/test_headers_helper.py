"""`sheaf headers`, the headersHelper of the door's MCP entry (SPEC 9.14, 13): Claude Code runs it when it connects the
door and sends what it prints as request headers, so a door write names the session, the machine and the Remote Control
link as a send does. `sheaf headers --check NAME` says whether an MCP entry carries it, for the mod. Run in a temp home
and a temp Claude config folder; the keyring is out of reach (premortem R7), because the helper has no business with a
token and its output holds none."""
import json
import os

import pytest

from sheafmd import cli, connect, send
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
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)   # Claude Code does not pass it to a headersHelper (live check, 2026-11-16)
    monkeypatch.setattr(send, "ancestor_pids", lambda: [900, 500, 1])   # the helper, a shell, claude (pid 500), init

    def record(pid=500, **more):
        (cfg / "sessions" / f"{pid}.json").write_text(json.dumps({"pid": pid, "sessionId": SESSION, **more}), encoding="utf-8")
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


def test_the_session_is_the_record_of_the_nearest_ancestor_never_the_inherited_variable(registry, monkeypatch, capsys):
    registry()
    other = "11111111-2222-4333-8444-555555555555"
    (send.config_dir_of(os.environ) / "sessions" / "1.json").write_text(json.dumps({"pid": 1, "sessionId": other}), encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", other)         # the parent shell's own id, inherited: not Claude's
    assert json.loads(run(capsys)[1])["X-Sheaf-Session"] == SESSION      # pid 500 comes before pid 1


def test_with_no_record_among_the_ancestors_it_sends_no_session_header(registry, monkeypatch, capsys):
    registry(pid=777)                                          # a record, but not of an ancestor
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)      # even with the variable set
    assert json.loads(run(capsys)[1]) == {"X-Sheaf-Host": "laptop-bea"}


def test_a_record_that_is_unreadable_or_has_no_session_id_is_no_record(registry, capsys):
    cfg = send.config_dir_of(os.environ)
    (cfg / "sessions" / "500.json").write_text("{not json")
    assert "X-Sheaf-Session" not in json.loads(run(capsys)[1])
    (cfg / "sessions" / "500.json").write_text(json.dumps({"pid": 500, "sessionId": ""}))
    assert "X-Sheaf-Session" not in json.loads(run(capsys)[1])


def test_ancestor_pids_walks_proc_stat_to_init(tmp_path):
    for pid, ppid in ((30, 20), (20, 10), (10, 1), (1, 0)):
        d = tmp_path / str(pid)
        d.mkdir()
        (d / "stat").write_text(f"{pid} (a b) c) S {ppid} 0 0\n")      # a name with spaces and a bracket
    assert send.ancestor_pids(30, proc=tmp_path) == [30, 20, 10, 1]


def test_with_no_session_it_still_prints_the_machine_and_exits_0(registry, capsys):
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


def test_check_says_yes_only_for_a_door_entry_that_carries_the_helper(claude_json, registry, capsys):
    registry()
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


def test_a_command_name_wins_over_a_file_or_folder_of_the_same_name(registry, claude_json, tmp_path, monkeypatch, capsys):
    registry()
    claude_json({connect.entry_name(ORIGIN): entry("sheaf headers")})
    work = tmp_path / "project"
    (work / "headers").mkdir(parents=True)                 # a C project's headers/ folder
    monkeypatch.chdir(work)
    opened = []
    monkeypatch.setattr(cli, "cmd_file", lambda argv: opened.append(argv) or 0)
    assert json.loads(run(capsys)[1])["X-Sheaf-Session"] == SESSION
    assert run(capsys, "--check", connect.entry_name(ORIGIN)) == (0, "", "")
    (work / "headers").rmdir()
    (work / "headers").write_text("a file")                # and a file of that name
    assert json.loads(run(capsys)[1])["X-Sheaf-Session"] == SESSION
    assert opened == []


def test_a_path_still_opens_a_document_even_when_it_is_named_like_a_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "headers").write_text("# Notes")
    (tmp_path / "headers.md").write_text("# Notes")
    opened = []
    monkeypatch.setattr(cli, "cmd_file", lambda argv: opened.append(argv) or 0)
    for given in ("./headers", "headers.md", "./headers.md"):
        assert main([given]) == 0
    assert opened == [["./headers"], ["headers.md"], ["./headers.md"]]


def proc_with(tmp_path, chain):
    for pid, ppid in chain:
        d = tmp_path / str(pid)
        d.mkdir(exist_ok=True)
        (d / "stat").write_text(f"{pid} (x) S {ppid} 0 0\n")
    return tmp_path


def test_without_proc_the_walk_asks_ps_for_each_parent(tmp_path):
    asked = []
    parents = {30: 20, 20: 10, 10: 1}

    def ps(pid):
        asked.append(pid)
        return parents.get(pid, 0)
    assert send.ancestor_pids(30, proc=tmp_path / "no-proc", ps=ps) == [30, 20, 10, 1]
    assert asked == [30, 20, 10, 1]


def test_proc_comes_first_and_ps_fills_only_what_proc_lacks(tmp_path):
    proc = proc_with(tmp_path, [(30, 20)])                  # /proc knows 30; 20 it does not
    assert send.ancestor_pids(30, proc=proc, ps=lambda pid: {20: 1}.get(pid, 0)) == [30, 20, 1]


def test_a_walk_that_neither_proc_nor_ps_can_make_stops_at_the_helper(tmp_path):
    def ps(pid):
        raise OSError("no ps")
    assert send.ancestor_pids(30, proc=tmp_path / "no-proc", ps=ps) == [30]


def test_the_walk_is_bounded_and_never_loops(tmp_path):
    assert len(send.ancestor_pids(1000, proc=tmp_path / "no-proc", ps=lambda pid: pid + 1)) <= send.MAX_ANCESTORS
    assert send.ancestor_pids(7, proc=tmp_path / "no-proc", ps=lambda pid: 7) == [7]


def test_ps_is_run_without_a_shell_with_a_timeout(monkeypatch):
    seen = {}

    class Done:
        stdout = " 42\n"
        returncode = 0

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return Done()
    monkeypatch.setattr(send.subprocess, "run", fake_run)
    assert send.ps_parent(9) == 42
    assert seen["argv"] == ["ps", "-o", "ppid=", "-p", "9"]
    assert not seen["kw"].get("shell") and seen["kw"]["timeout"] > 0


def test_check_exits_1_with_one_plain_line_when_no_ancestor_has_a_record(claude_json, registry, capsys):
    claude_json({connect.entry_name(ORIGIN): entry("sheaf headers")})      # the entry has the helper, but this walk finds no record
    code, out, err = run(capsys, "--check", connect.entry_name(ORIGIN))
    assert code == 1 and out == "" and len(err.strip().splitlines()) == 1 and "session" in err
