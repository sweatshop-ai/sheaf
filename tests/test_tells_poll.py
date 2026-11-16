"""`sheaf tells-poll --origin O --session S --wait N`: one long-poll of a tiroir's door for a laptop session's Tells
(SPEC 9.8, 13), for the Claude Code mod of the plugin. It prints the Tells as a JSON array and reads the token from the
keyring, so the token never enters the mod. Run in a temp home with a fake keyring and a fake door (premortem R7: no
test reads the real keyring or `~/.claude.json`); the hub-backed tests at the end stand the door up as the tiroir."""
import json
import re

import pytest
from helpers import FRONT
from test_session_tells import SESSION, declare, laptops, poll, tell  # noqa: F401  (laptops is a fixture)
from test_hub_waiting import talk  # noqa: F401  (fixture)

from sheafmd import connect, send
from sheafmd.cli import main

TELL = {"id": "t1", "doc": "loose-bea/notes.md", "thread": "c1", "message": "Please look at this.", "by": "Cal", "at": "now"}


class FakeKeyring:
    def __init__(self, **tokens):
        self.items = {("sheaf", origin): t for origin, t in tokens.items()}

    def get(self, service, user):
        return self.items.get((service, user))


@pytest.fixture(autouse=True)
def no_real_keyring(monkeypatch):
    def refuse():
        raise AssertionError("a test asked for the real keyring (R7): inject a FakeKeyring")
    monkeypatch.setattr(connect, "system_store", refuse)


@pytest.fixture
def keyring(monkeypatch):
    k = FakeKeyring(**{FRONT: "secret-token-of-bea"})
    monkeypatch.setattr(connect, "system_store", lambda: k)
    return k


class FakeDoor:
    """Answers `send.post` as a tiroir's door: `tells` gives `tells` (or an error), everything else is the handshake."""

    def __init__(self, monkeypatch, tells=(), error=None, status=200, body=None):
        self.seen, self.tells, self.error, self.status, self.body = [], list(tells), error, status, body
        monkeypatch.setattr(send, "post", self.post)

    def post(self, url, bearer, message, headers):
        self.seen.append((url, bearer, message, dict(headers)))
        if self.status != 200:
            return self.status, None, {}
        if message.get("method") == "initialize":
            return 200, {"jsonrpc": "2.0", "id": message["id"], "result": {"protocolVersion": send.PROTOCOL}}, {}
        if message.get("method") != "tools/call":
            return 202, None, {}
        text = self.error if self.error else self.body if self.body is not None else json.dumps({"tells": self.tells})
        return 200, {"jsonrpc": "2.0", "id": message["id"],
                     "result": {"content": [{"type": "text", "text": text}], "isError": bool(self.error)}}, {}

    def calls(self):
        return [m for _, _, m, _ in self.seen if m.get("method") == "tools/call"]


def run(capsys, *argv):
    code = main(["tells-poll", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_it_prints_the_tells_the_door_gave_as_a_json_array(keyring, monkeypatch, capsys):
    door = FakeDoor(monkeypatch, tells=[TELL])
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION, "--wait", "25")
    assert code == 0 and err == ""
    assert json.loads(out) == [TELL]
    assert door.calls()[0]["params"] == {"name": "tells", "arguments": {"wait": 25}}


def test_it_prints_an_empty_array_when_nothing_waits(keyring, monkeypatch, capsys):
    FakeDoor(monkeypatch)
    code, out, _ = run(capsys, "--origin", FRONT, "--session", SESSION)
    assert (code, json.loads(out)) == (0, [])


def test_the_session_travels_in_the_declared_header_and_the_token_is_the_keyrings(keyring, monkeypatch, capsys):
    door = FakeDoor(monkeypatch)
    run(capsys, "--origin", FRONT, "--session", SESSION, "--wait", "0")
    assert {h.get("X-Sheaf-Session") for *_, h in door.seen} == {SESSION}
    assert {b for _, b, *_ in door.seen} == {"secret-token-of-bea"}
    assert all(u == FRONT + "/mcp" for u, *_ in door.seen)


def test_no_output_holds_the_token(keyring, monkeypatch, capsys):
    FakeDoor(monkeypatch, error="boom secret-token-of-bea")
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION)
    assert code == 1
    assert "secret-token-of-bea" not in out + err


def test_an_origin_with_no_credential_is_refused_without_a_request(monkeypatch, capsys):
    monkeypatch.setattr(connect, "system_store", lambda: FakeKeyring())
    door = FakeDoor(monkeypatch)
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION)
    assert code == 1 and out == "" and "sheaf connect" in err and door.seen == []


def test_a_token_of_another_origin_is_never_sent_to_this_one(monkeypatch, capsys):
    monkeypatch.setattr(connect, "system_store", lambda: FakeKeyring(**{"https://other.example.com": "other-token"}))
    door = FakeDoor(monkeypatch)
    assert run(capsys, "--origin", FRONT, "--session", SESSION)[0] == 1
    assert door.seen == []


@pytest.mark.parametrize("origin", ["http://chat.example.com", "chat.example.com", "https://chat.example.com/x?y", ""])
def test_an_origin_that_is_not_a_door_address_is_refused(keyring, monkeypatch, capsys, origin):
    door = FakeDoor(monkeypatch)
    code, out, err = run(capsys, "--origin", origin, "--session", SESSION)
    assert code == 1 and out == "" and door.seen == []


def test_a_refused_token_and_a_busy_door_exit_non_zero_with_the_sentence_on_stderr(keyring, monkeypatch, capsys):
    FakeDoor(monkeypatch, status=401)
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION)
    assert code == 1 and out == "" and "refused the token" in err
    FakeDoor(monkeypatch, error="This token already holds 2 polls: wait 5 seconds.")
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION)
    assert code == 1 and out == "" and "wait 5 seconds" in err


@pytest.mark.parametrize("body", ['{"other": 1}', '[]', '{"tells": "none"}', '{"tells": [3]}', 'null', 'not json'])
def test_an_answer_of_the_wrong_shape_exits_1_with_one_line_and_no_traceback(keyring, monkeypatch, capsys, body):
    FakeDoor(monkeypatch, body=body)
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION)
    assert code == 1 and out == ""
    assert err.startswith("sheaf: ") and len(err.strip().splitlines()) == 1 and "Traceback" not in err


def test_a_server_name_of_the_mcp_entries_finds_its_origin_and_polls_it(keyring, monkeypatch, capsys, tmp_path):
    door = FakeDoor(monkeypatch, tells=[TELL])
    name = connect.entry_name(FRONT)
    cj = tmp_path / ".claude.json"
    cj.write_text(json.dumps({"mcpServers": {name: {"type": "http", "url": FRONT + connect.DOOR_PATH,
                                                     "headers": {"Authorization": "Bearer other-token"}}}}))
    monkeypatch.setattr(connect, "claude_json", lambda: cj)
    for given in (name, re.sub(r"[^A-Za-z0-9_-]", "_", name)):     # the entry's key, and as a tool name writes it
        code, out, err = run(capsys, "--server", given, "--session", SESSION)
        assert code == 0 and json.loads(out) == [TELL]
    assert door.seen[0][0].startswith(FRONT) and all(b == "secret-token-of-bea" for _, b, _, _ in door.seen)


def test_a_server_that_is_not_a_sheaf_door_entry_is_refused_without_a_request(keyring, monkeypatch, capsys, tmp_path):
    door = FakeDoor(monkeypatch)
    cj = tmp_path / ".claude.json"
    cj.write_text(json.dumps({"mcpServers": {"mine": {"type": "http", "url": "https://elsewhere.example/mcp"},
                                             connect.entry_name(FRONT): {"type": "http", "url": "https://elsewhere.example/mcp"}}}))
    monkeypatch.setattr(connect, "claude_json", lambda: cj)
    for name in ("mine", connect.entry_name(FRONT), "sheaf-nothing"):
        code, out, err = run(capsys, "--server", name, "--session", SESSION)
        assert code == 1 and out == "" and err.startswith("sheaf: ")
    assert door.seen == []


def test_origin_and_server_are_given_one_at_a_time(keyring, monkeypatch, capsys):
    FakeDoor(monkeypatch)
    for argv in (["--session", SESSION], ["--origin", FRONT, "--server", "sheaf-x", "--session", SESSION]):
        code, out, _ = run(capsys, *argv)
        assert code == 2 and out == ""


def test_a_tiroir_that_is_down_exits_non_zero(keyring, monkeypatch, capsys):
    def down(url, bearer, message, headers):
        raise send.Unreachable("cannot reach chat.example.com: refused. Nothing was sent.")
    monkeypatch.setattr(send, "post", down)
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION)
    assert code == 1 and out == "" and "cannot reach" in err


@pytest.mark.parametrize("wait", ["-1", "26", "x"])
def test_a_wait_outside_0_to_25_is_refused_before_any_request(keyring, monkeypatch, capsys, wait):
    door = FakeDoor(monkeypatch)
    code, out, err = run(capsys, "--origin", FRONT, "--session", SESSION, "--wait", wait)
    assert code != 0 and out == "" and "0 to 25" in err and door.seen == []


def test_the_poll_waits_longer_than_a_tool_call_does(monkeypatch):
    """The door holds up to 25 s; the request's timeout must outlast it, or every empty poll would fail."""
    seen = []
    monkeypatch.setattr(send, "_request", lambda req, timeout=send.TIMEOUT: seen.append(timeout) or (200, None, {}))
    send.post(FRONT + "/mcp", "t", {"method": "tools/call", "params": {"name": "tells"}}, {})
    send.post(FRONT + "/mcp", "t", {"method": "tools/call", "params": {"name": "read"}}, {})
    assert seen[0] > 25 + 5 and seen[1] == send.TIMEOUT


# ── against the hub as the tiroir (R21) ─────────────────────────────────────

@pytest.fixture
def at_hub(laptops, monkeypatch):  # noqa: F811
    """`send.post` goes into the hub's door with the bearer it was given: the CLI's own request, the hub's own answer."""
    from helpers import door, rpc  # noqa: F401

    def post(url, bearer, message, headers):
        res = door(laptops.door, message, token=bearer, headers=dict(headers), as_name=None)
        return res.status, (res.json() if res.status == 200 else None), {}
    monkeypatch.setattr(send, "post", post)

    def keyring_of(who):
        monkeypatch.setattr(connect, "system_store", lambda: FakeKeyring(**{FRONT: laptops.tokens[who]}))
    return keyring_of


def got(capsys, *argv):
    code, out, err = run(capsys, "--origin", FRONT, *argv)
    return code, (json.loads(out) if out else None), err


def test_the_session_that_declared_gets_its_tell_through_the_cli(laptops, at_hub, capsys):  # noqa: F811
    declare(laptops)
    tell(laptops)
    at_hub("bea-one")
    code, tells, _ = got(capsys, "--session", SESSION, "--wait", "0")
    assert code == 0 and [t["thread"] for t in tells] == ["c1"] and tells[0]["by"]


def test_a_second_laptop_of_the_same_member_with_the_same_session_id_gets_nothing(laptops, at_hub, capsys):  # noqa: F811
    declare(laptops)
    tell(laptops)
    at_hub("bea-two")
    assert got(capsys, "--session", SESSION, "--wait", "0")[:2] == (0, [])


def test_another_members_laptop_replaying_the_session_id_gets_nothing(laptops, at_hub, capsys):  # noqa: F811
    declare(laptops)
    tell(laptops)
    at_hub("cal-one")
    assert got(capsys, "--session", SESSION, "--wait", "0")[:2] == (0, [])


def test_the_right_laptop_with_another_session_id_gets_nothing(laptops, at_hub, capsys):  # noqa: F811
    declare(laptops)
    tell(laptops)
    at_hub("bea-one")
    assert got(capsys, "--session", "another-session", "--wait", "0")[:2] == (0, [])
