"""`sheaf mcp`: the stdio door (SPEC 12). It forwards each JSON-RPC line to `POST /_/mcp` on the
hub with the key and a name, and writes back what the hub answers.

Four levels: the line framing against the handler in memory; the link to a real hub on a socket
(a hub on a thread of this process); the link to a stand-in hub that a test controls, for what a
real hub cannot be made to do on cue (lose its port between two requests, end a connection, refuse
once); and the command as a real process that starts its own hub."""
import io
import itertools
import json
import os
import re
import select
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

import helpers
import sheafmd.comments as rdc
from helpers import PLAN, comment, door, rpc
from sheafmd import __version__, mcp, paths
from sheafmd.hub import client, server
from sheafmd.hub.auth import Auth
from sheafmd.hub.core import Hub
from sheafmd.hub.roots import Roots
from sheafmd.hub.service import ServiceError
from sheafmd.source import md_hash, update_file

DOC = "work/plan.md"
HOLD = 2                    # seconds that a stand-in hub keeps a connection open and says nothing


def lines(*messages):
    return b"".join(json.dumps(m).encode() + b"\n" for m in messages)


def run_stdio(post, data):
    out, err = io.BytesIO(), io.StringIO()
    code = mcp.Stdio(post, io.BytesIO(data), out, err).run()
    return code, [json.loads(x) for x in out.getvalue().splitlines()], out.getvalue(), err.getvalue()


@pytest.fixture
def to_hub(browser):
    """What `sheaf mcp` does for each line, with the handler in memory in place of the socket."""
    def post(raw):
        res = door(browser, raw=raw, as_name="Claude")
        return res.status, res.body
    return post


def test_the_help_of_the_stdio_command_and_of_init_call_it_the_door_not_a_server(sheaf):
    """GLOSSARY: MCP door, avoid "MCP server"."""
    for argv in (["mcp", "--help"], ["init", "--help"]):
        assert "server" not in sheaf(*argv).out.lower(), argv
    assert "mcp door" in sheaf("mcp", "--help").out.lower()


def test_the_module_docstring_names_only_files_that_exist():
    named = set(re.findall(r"\b\w+\.py\b", mcp.__doc__))
    found = {f.name for f in Path(mcp.__file__).parent.rglob("*.py")}
    assert named and named <= found, named - found


# ── whose name the replies carry ─────────────────────────────────────────────

@pytest.mark.parametrize("agent,env,want", [
    ("claude-code", {}, "Claude"), ("codex", {}, "Codex"), ("gemini", {}, "Gemini"),
    ("cursor", {}, "Cursor"), ("opencode", {}, "opencode"),
    ("Some Agent", {}, "Some Agent"),                                   # a name sheaf does not know
    ("codex", {"CLAUDE_CODE_SESSION_ID": "s1"}, "Codex"),               # --agent wins
    (None, {"CLAUDE_CODE_SESSION_ID": "s1"}, "Claude"),                 # else what it sees around it
    (None, {"CODEX_THREAD_ID": "t1"}, "Codex"),
    ("", {"CLAUDE_CODE_SESSION_ID": "s1"}, "Claude"),
    (None, {}, "agent"), ("   ", {}, "agent"),
    ("\x07", {}, "agent"), ("​​", {"CLAUDE_CODE_SESSION_ID": "s1"}, "Claude"),  # nothing the hub keeps
])
def test_replies_are_signed_with_the_agent_named_else_detected_else_agent(agent, env, want):
    assert mcp.display_for(agent, env) == want


# ── the lines ────────────────────────────────────────────────────────────────

def test_each_request_line_gets_one_answer_line_with_its_id(to_hub):
    code, got, raw, _ = run_stdio(to_hub, lines(rpc("ping", id=1), rpc("ping", id="b"),
                                                rpc("tools/list", id=3)))
    assert code == 0 and [g["id"] for g in got] == [1, "b", 3]
    assert got[0]["result"] == {} and len(got[2]["result"]["tools"]) == 7
    assert raw.count(b"\n") == 3 and raw.endswith(b"\n")


def test_a_notification_is_forwarded_and_says_nothing_back(to_hub):
    code, got, raw, err = run_stdio(to_hub, lines(rpc("notifications/initialized", id=None),
                                                  rpc("ping", id=2)))
    assert [g["id"] for g in got] == [2] and err == ""


def test_blank_lines_and_windows_line_ends_are_fine(to_hub):
    data = b"\n  \n" + json.dumps(rpc("ping")).encode() + b"\r\n\r\n"
    _, got, _, _ = run_stdio(to_hub, data)
    assert len(got) == 1 and got[0]["result"] == {}


def test_what_the_hub_calls_a_bad_message_is_passed_on_as_it_is(to_hub):
    _, got, _, _ = run_stdio(to_hub, b"{not json\n" + lines([rpc("ping")]))
    assert [g["error"]["code"] for g in got] == [-32700, -32600]
    assert all(g["id"] is None for g in got)


def test_an_answer_with_line_breaks_in_its_text_stays_on_one_line(browser, plan, to_hub):
    comment(plan, body="Line one\nline two")
    msg = rpc("tools/call", {"name": "threads", "arguments": {"doc": DOC}})
    _, got, raw, _ = run_stdio(to_hub, lines(msg))
    assert raw.count(b"\n") == 1
    said = json.loads(got[0]["result"]["content"][0]["text"])
    assert said["comments"][0]["body"] == "Line one\nline two"


def test_a_refusal_that_is_not_json_rpc_becomes_an_error_for_the_request_that_asked(browser):
    def post(raw):
        return 413, b'{"ok": false, "error": "the request is too large"}'
    _, got, _, err = run_stdio(post, lines(rpc("ping", id=7)))
    [g] = got
    assert g["id"] == 7 and g["error"]["code"] == -32603 and "too large" in g["error"]["message"]
    assert "too large" in err                                  # and the person who runs the agent can read why


def test_the_same_refusal_for_a_notification_is_only_written_to_stderr():
    def post(raw):
        return 500, b'{"ok": false, "error": "the hub failed on this request"}'
    _, got, raw, err = run_stdio(post, lines(rpc("notifications/initialized", id=None)))
    assert got == [] and raw == b"" and "the hub failed" in err


def test_a_hub_that_cannot_be_reached_is_an_error_for_each_request_and_the_door_stays_up():
    def post(raw):
        raise client.HubUnavailable("the hub did not start; see `sheaf diag`")
    code, got, raw, err = run_stdio(post, lines(rpc("initialize", id=1), rpc("ping", id=2),
                                                rpc("notifications/initialized", id=None)))
    assert code == 0 and [g["id"] for g in got] == [1, 2]
    assert all(g["error"]["code"] == -32603 and "did not start" in g["error"]["message"] for g in got)
    assert "did not start" in err


def test_stdout_holds_nothing_but_protocol_lines(to_hub):
    _, _, raw, _ = run_stdio(to_hub, lines(rpc("initialize", {"protocolVersion": "2025-06-18"}),
                                           rpc("tools/list", id=2), rpc("ping", id=3)))
    for line in raw.splitlines():
        assert json.loads(line)["jsonrpc"] == "2.0"


def test_a_closed_stdout_ends_the_door_quietly(to_hub):
    class Gone(io.BytesIO):
        def write(self, b):
            raise BrokenPipeError
    assert mcp.Stdio(to_hub, io.BytesIO(lines(rpc("ping"))), Gone(), io.StringIO()).run() == 0


# ── the link to a hub on a socket ────────────────────────────────────────────

@pytest.fixture
def served(work, monkeypatch):
    """A running hub on a free port that the commands of this test reach as their own:
    (hub, plan file, the server that a test may close to take the hub away)."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    monkeypatch.setenv("SHEAF_PORT", str(port))
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    comment(f)
    yield hub, f, srv
    srv.close()


@pytest.fixture
def live(served):
    hub, f, _ = served
    return hub, f


def said(link, message):
    status, body = link.post(json.dumps(message).encode())
    return status, (json.loads(body) if body else None)


def test_the_link_proves_the_hub_then_sends_the_key_and_the_name(live):
    hub, f = live
    link = client.DoorLink("Claude Code", say=lambda s: None)
    assert said(link, rpc("ping"))[0] == 200
    status, got = said(link, rpc("tools/call", {"name": "reply", "arguments": {
        "doc": DOC, "id": "c1", "text": "Through a socket.", "role": "action"}}))
    assert status == 200 and not got["result"]["isError"]
    r = rdc.parse(f.read_text(encoding="utf-8")).by_id("c1").replies[-1]
    assert (r.by, r.role, r.text) == ("Claude Code", "action", "Through a socket.")


@pytest.mark.parametrize("name", ["Zoë", "Naïve Agent ✓", "100% sure", "a%41b"])
def test_a_name_that_is_not_ascii_or_holds_a_percent_arrives_as_it_was_given(live, name):
    hub, f = live
    link = client.DoorLink(name, say=lambda s: None)
    said(link, rpc("tools/call", {"name": "reply", "arguments": {"doc": DOC, "id": "c1", "text": "x"}}))
    assert rdc.parse(f.read_text(encoding="utf-8")).by_id("c1").replies[-1].by == name


def test_an_answer_of_several_megabytes_comes_whole(live):
    hub, f = live
    update_file(f, lambda t: rdc.reply(t, "c1", "word " * 500_000, "Ada", "2026-10-14T10:05"))
    link = client.DoorLink("Claude", say=lambda s: None)
    status, got = said(link, rpc("tools/call", {"name": "threads", "arguments": {"doc": DOC,
                                                                               "status": "all"}}))
    assert status == 200 and len(got["result"]["content"][0]["text"]) > 2_000_000


def test_sheaf_rotate_while_the_door_runs_makes_it_read_the_key_again(live, sheaf):
    """The real `/_/rotate`: the hub writes a new key and uses it at once; the door still holds
    the old one, so its proof fails before anything is sent, and it reads the key again."""
    hub, f = live
    link = client.DoorLink("Claude", say=lambda s: None)
    assert said(link, rpc("ping"))[0] == 200
    old = paths.key_file().read_text(encoding="ascii")
    assert sheaf("rotate").code == 0
    assert paths.key_file().read_text(encoding="ascii") != old
    status, got = said(link, rpc("tools/call", {"name": "reply", "arguments": {
        "doc": DOC, "id": "c1", "text": "After the rotation."}}))
    assert status == 200 and not got["result"]["isError"]
    assert [r.text for r in rdc.parse(f.read_text(encoding="utf-8")).by_id("c1").replies] == ["After the rotation."]
    assert said(link, rpc("ping", id=3))[1]["id"] == 3


def stranger(port=0):
    """Something that is not a hub holding a port: (its socket, the requests it was sent)."""
    seen = []
    s = helpers.Listener()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(5)

    def serve():
        while True:
            try:
                c, _ = s.accept()
            except OSError:
                return
            seen.append(c.recv(65536))
            c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
            c.close()
    s.thread = threading.Thread(target=serve, daemon=True)
    s.thread.start()
    return s, seen


def never_sent(seen):
    key = paths.key_file().read_text(encoding="ascii").strip().encode()
    return bool(seen) and all(key not in req and b"/_/mcp" not in req for req in seen)


def test_something_else_on_the_port_is_never_sent_the_key(work, monkeypatch):
    s, seen = stranger()
    monkeypatch.setenv("SHEAF_PORT", str(s.getsockname()[1]))
    link = client.DoorLink("Claude", say=lambda s: None)
    with pytest.raises(client.HubUnavailable, match="something else holds"):
        link.post(json.dumps(rpc("ping")).encode())
    s.close()
    assert never_sent(seen)


def test_a_hub_that_a_stranger_replaces_after_the_proof_is_not_sent_the_key(served):
    """The door lives as long as the agent does. The proof it had at the start says nothing
    about what answers on the port an hour later (SPEC 9.4)."""
    hub, f, srv = served
    link = client.DoorLink("Claude", say=lambda s: None)
    assert said(link, rpc("ping"))[0] == 200
    srv.close()                                                  # the hub is gone ...
    s, seen = stranger(hub.port)                                 # ... and something else holds its port
    with pytest.raises(client.HubUnavailable, match="something else holds"):
        link.post(json.dumps(rpc("ping", id=2)).encode())
    s.close()
    assert never_sent(seen)


class StandInHub:
    """A hub on a port of its own that proves itself with the real key and writes down, for each
    connection, what was asked on it: `log` holds (connection, method, path), `headers` those of
    each request but the proofs. `at_proof(n)` runs when the n-th proof is asked, before it is
    sent, and answers True to end that connection after it (saying so, `Connection: close`), "fin"
    to end it after it without a word, "silent" to end it with no answer at all, "hold" to answer
    nothing and keep it open. `on_request` says, for a path, what the hub does with a request that
    reached it: "close" ends the connection with no answer, "hold" keeps it open and answers
    nothing. `ending` is whether the last proof was one that the hub ended without a word. `refusals`
    is how many of the next messages get a 401. `answers` is what a command's
    route says (`{"ok": true}` when a path is not in it), and `version` and `service` what the
    proof says the hub runs and whether the service does."""

    started = []                                # every stand-in of the running test, for `shut_all`

    def __init__(self, version=__version__, service=False):
        key, owner = paths.ensure_key(), self
        self.log, self.headers, self.proofs, self.refusals = [], [], 0, 0
        self.at_proof, self.on_request, self.ending = lambda n: False, {}, False
        self.answers = {"/_/jobs": {"ok": True, "asking": [], "telling": []}}
        numbers = itertools.count(1)            # a connection's number; `id(handler)` is reused once it is freed

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self):
                super().setup()
                self.number = next(numbers)

            def log_message(self, *a):
                pass

            def reply(self, body, end=False, status=200):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                if end:
                    self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def drop_request(self, path):
                """Do what `on_request` says with this request, and end its connection after: True when
                there was something to do, so that the request is not answered."""
                how = owner.on_request.get(path)
                if how == "hold":
                    threading.Event().wait(HOLD)
                if how:
                    self.close_connection = True
                return bool(how)

            def do_GET(self):
                path = urlsplit(self.path).path
                owner.log.append((self.number, "GET", path))
                if path != "/_/health":
                    owner.headers.append(dict(self.headers))
                    if self.drop_request(path):
                        return
                    return self.reply(json.dumps(owner.answers.get(path, {"ok": True})).encode())
                nonce = parse_qs(urlsplit(self.path).query)["nonce"][0]
                owner.proofs += 1
                then = owner.at_proof(owner.proofs)
                owner.ending = then == "fin"
                if then == "silent":
                    self.close_connection = True
                    return
                if then == "hold":
                    return threading.Event().wait(HOLD)
                self.reply(json.dumps({"app": "sheaf", "version": version, "boot": "b", "service": service,
                                       "proof": Auth(key, owner.port).proof(nonce)}).encode(), then is True)
                if then == "fin":
                    self.close_connection = True

            def do_DELETE(self):
                """A hub of the version before this has no DELETE route: it answers 405."""
                path = urlsplit(self.path).path
                owner.log.append((self.number, "DELETE", path))
                owner.headers.append(dict(self.headers))
                if self.drop_request(("DELETE", path)):
                    return
                self.reply(b'{"ok": false, "error": "method not allowed"}', status=405)

            def do_POST(self):
                owner.log.append((self.number, "POST", self.path))
                owner.headers.append(dict(self.headers))
                body = self.rfile.read(int(self.headers["Content-Length"]))
                said = json.loads(body) if body else {}
                if self.drop_request(self.path):
                    return
                if owner.refusals:
                    owner.refusals -= 1
                    return self.reply(b'{"ok": false, "error": "the key is not the hub\'s"}', status=401)
                if self.path == "/_/mcp":
                    return self.reply(json.dumps({"jsonrpc": "2.0", "id": said["id"], "result": {}}).encode())
                self.reply(json.dumps(owner.answers.get(self.path, {"ok": True})).encode())

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        StandInHub.started.append(self)         # only a stand-in that is listening has something to end

    @classmethod
    def shut_all(cls):
        """End every stand-in that was started: its listener and its `serve_forever` thread."""
        while cls.started:
            cls.started.pop().lose_the_port()

    def lose_the_port(self):
        """The hub ends, as one does between two requests, and the port is free for anyone."""
        self.httpd.shutdown()
        self.httpd.server_close()

    def connections_that_carried_a_message(self):
        """What was asked on each connection that carried a message, in order."""
        by_connection = {}
        for conn, method, path in self.log:
            by_connection.setdefault(conn, []).append(f"{method} {path}")
        return [asked for asked in by_connection.values() if "POST /_/mcp" in asked]


@pytest.fixture(autouse=True)
def stand_in_hubs_end_with_their_test():
    """Every StandInHub a test started is shut down when the test ends: its listener and its thread."""
    yield
    StandInHub.shut_all()


HOW_A_HUB_ENDS_A_CONNECTION = pytest.mark.parametrize("ends", [True, "fin"], ids=["and_says_so", "without_a_word"])


def wait_for_the_fin(monkeypatch, stand_in):
    """Make a test of a connection that the hub ended without a word certain: the FIN is on its way as the
    proof is read, but a test that depends on the race flakes. After each proof that the stand-in
    ends, wait until the FIN has arrived."""
    real = client.HubClient._prove_on

    def prove_then_wait(self, c):
        got = real(self, c)
        if stand_in.ending:
            assert select.select([c.sock], [], [], 10)[0], "the stand-in's FIN did not arrive"
        return got
    monkeypatch.setattr(client.HubClient, "_prove_on", prove_then_wait)


def test_a_stand_in_hub_that_is_shut_down_frees_its_port(work):
    stand_in = StandInHub()
    StandInHub.shut_all()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", stand_in.port), timeout=2).close()


def test_the_name_goes_in_the_header_as_percent_encoded_utf8(work):
    stand_in = StandInHub()
    client.HubClient(paths.ensure_key(), stand_in.port).door(b'{"id": 1}', "Zoë 100%")
    assert stand_in.headers[0]["X-Sheaf-As"] == "Zo%C3%AB 100%25"
    assert stand_in.headers[0]["X-Sheaf-Key"] == paths.key_file().read_text(encoding="ascii").strip()


def test_a_hub_that_a_stranger_replaces_between_the_proof_and_the_message_is_not_sent_the_message(
        work, monkeypatch):
    """The proof and the message went on two connections, and whatever took the port in between
    got the key and the name (SPEC 9.4)."""
    stand_in, held = StandInHub(), []
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    link = client.DoorLink("Claude", say=lambda s: None)
    assert said(link, rpc("ping"))[0] == 200                     # the door is up and knows its hub

    def swap(n):                                                 # the next proof is made, then the hub is gone
        stand_in.lose_the_port()
        held.append(stranger(stand_in.port))
        return False
    stand_in.at_proof = swap
    status, got = said(link, rpc("ping", id=2))
    s, seen = held[0]
    s.close()
    assert seen == []                                            # the stranger was sent nothing
    assert (status, got["id"]) == (200, 2)                       # the hub that proved itself answered


@HOW_A_HUB_ENDS_A_CONNECTION
def test_a_message_goes_only_on_a_connection_that_proved_the_hub(work, monkeypatch, ends):
    """A hub that ends the connection after its proof, whether it says so or not, must not make the door
    open another one for the message: it proves again, on the connection the message then goes on."""
    stand_in = StandInHub()
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    link = client.DoorLink("Claude", say=lambda s: None)
    assert said(link, rpc("ping"))[0] == 200
    ending = stand_in.proofs + 1
    stand_in.at_proof = lambda n: ends if n == ending else False        # the next proof ends its connection
    wait_for_the_fin(monkeypatch, stand_in)
    assert said(link, rpc("ping", id=2))[1]["id"] == 2
    carried = stand_in.connections_that_carried_a_message()
    assert len(carried) == 2                                     # each message was sent once
    assert all(asked[asked.index("POST /_/mcp") - 1] == "GET /_/health" for asked in carried)


def test_a_key_that_is_refused_after_the_proof_is_read_again_once_and_the_message_goes_again(
        work, monkeypatch):
    """A rotation between the proof and the message, on the connection that proved: a 401 is a
    refusal before anything was done, so the message may go again, once, with the key read again."""
    stand_in = StandInHub()
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    link = client.DoorLink("Claude", say=lambda s: None)
    stand_in.refusals = 1
    status, got = said(link, rpc("ping", id=7))
    assert (status, got["id"]) == (200, 7)
    assert [asked[-1] for asked in stand_in.connections_that_carried_a_message()] == ["POST /_/mcp"] * 2
    stand_in.refusals = 2                                        # refused again: the second 401 is the answer
    assert said(link, rpc("ping", id=8))[0] == 401


@pytest.mark.parametrize("proof_stalls_first", [False, True], ids=["answer_lost", "after_a_slow_proof"])
def test_a_message_the_hub_may_have_applied_is_never_sent_twice(served, monkeypatch, proof_stalls_first):
    """The answer was lost after the hub had written the reply: sending the same message again
    would write it a second time. With a first proof that stalled, nothing had reached the hub, so
    the door proves again and it is the answer to that second try that is lost."""
    hub, f, _ = served
    real, sent, stalled = client.HubClient.door, [], proof_stalls_first

    def answer_lost(self, raw, display):
        nonlocal stalled
        if stalled:
            stalled = False
            raise client.HubSilent(self.port)                    # nothing reached the hub
        out = real(self, raw, display)                           # a proof that fails in here sent nothing
        sent.append(raw)
        if len(sent) == 1:
            raise ConnectionResetError("connection reset by peer")
        return out
    monkeypatch.setattr(client.HubClient, "door", answer_lost)
    link = client.DoorLink("Claude", say=lambda s: None)
    reply = rpc("tools/call", {"name": "reply", "arguments": {"doc": DOC, "id": "c1", "text": "Once."}})
    with pytest.raises(client.HubUnavailable, match="may have"):
        link.post(json.dumps(reply).encode())
    assert len(sent) == 1
    assert [r.text for r in rdc.parse(f.read_text(encoding="utf-8")).by_id("c1").replies] == ["Once."]
    assert said(link, rpc("ping", id=3))[1]["id"] == 3           # the door stays up for the next message


# ── every other request that carries the key: a command's, and the door's start-up check ────────────

def key_of_the_test():
    return paths.key_file().read_text(encoding="ascii").strip()


def swapping_at(stand_in, at=1):
    """An `at_proof` that takes the hub away when proof number `at` is asked, after answering it: its
    port is held by a stranger from the next connection on. Returns it with the list that gets the stranger."""
    held = []

    def swap(n):
        if n == at:
            stand_in.lose_the_port()
            held.append(stranger(stand_in.port))
        return False
    return swap, held


def only_proofs(seen):
    """What a stranger was sent was a proof and nothing else: no key, no route of the hub."""
    return bool(seen) and all(req.startswith(b"GET /_/health?nonce=") and key_of_the_test().encode() not in req
                              for req in seen)


def asked_before(stand_in, method, path):
    """For each request of `method path`, what was asked just before it on its own connection."""
    by_connection = {}
    for conn, m, p in stand_in.log:
        by_connection.setdefault(conn, []).append(f"{m} {p}")
    return [asked[asked.index(f"{method} {path}") - 1] if asked.index(f"{method} {path}") else None
            for asked in by_connection.values() if f"{method} {path}" in asked]


def test_a_commands_request_goes_on_the_connection_that_proved_the_hub(work):
    stand_in = StandInHub()
    c = client.HubClient(paths.ensure_key(), stand_in.port)
    assert c.call("POST", "/_/render", {"path": "x"}) == (200, {"ok": True})
    assert c.call("GET", "/_/jobs")[0] == 200
    assert asked_before(stand_in, "POST", "/_/render") == ["GET /_/health"]
    assert asked_before(stand_in, "GET", "/_/jobs") == ["GET /_/health"]
    assert [h["X-Sheaf-Key"] for h in stand_in.headers] == [key_of_the_test()] * 2


def test_a_hub_that_a_stranger_replaces_between_the_proof_and_a_commands_request_is_not_sent_it(work):
    """The challenge and the call were two connections, and whatever took the port in between got
    the key and the request (SPEC 9.4)."""
    stand_in = StandInHub()
    stand_in.at_proof, held = swapping_at(stand_in)
    status, got = client.HubClient(paths.ensure_key(), stand_in.port).call("POST", "/_/render", {"path": "x"})
    s, seen = held[0]
    s.close()
    assert seen == []                                            # the stranger was sent nothing
    assert (status, got) == (200, {"ok": True})                  # the hub that proved itself answered
    assert stand_in.proofs == 1


def test_a_hub_replaced_after_a_challenge_is_not_sent_a_commands_request(work):
    stand_in = StandInHub()
    c = client.HubClient(paths.ensure_key(), stand_in.port)
    stand_in.at_proof, held = swapping_at(stand_in)
    assert c.challenge()["app"] == "sheaf"                       # what a command does first
    with pytest.raises(client.Impostor, match="something else holds"):
        c.call("POST", "/_/stop", {"reason": "stop"})
    s, seen = held[0]
    s.close()
    assert only_proofs(seen)
    assert [m for _, m, _ in stand_in.log if m == "POST"] == []


@pytest.mark.parametrize("how", ["silent", "hold"])
def test_a_hub_that_does_not_answer_the_proof_of_a_call_is_silent_not_a_stranger_and_is_sent_nothing(
        work, monkeypatch, how):
    monkeypatch.setattr(client, "TIMEOUT", 0.3)
    stand_in = StandInHub()
    stand_in.at_proof = lambda n: how
    with pytest.raises(client.HubSilent) as e:
        client.HubClient(paths.ensure_key(), stand_in.port).call("POST", "/_/render", {"path": "x"})
    assert "did not answer" in str(e.value) and "something else" not in str(e.value)
    assert [m for _, m, _ in stand_in.log if m == "POST"] == [] and stand_in.headers == []


@HOW_A_HUB_ENDS_A_CONNECTION
def test_a_hub_that_ends_the_connection_after_its_proof_is_asked_again_and_the_request_goes_once(
        work, monkeypatch, ends):
    stand_in = StandInHub()
    stand_in.at_proof = lambda n: ends if n == 1 else False      # the first proof ends its connection
    wait_for_the_fin(monkeypatch, stand_in)
    status, got = client.HubClient(paths.ensure_key(), stand_in.port).call("POST", "/_/render", {"path": "x"})
    assert (status, got) == (200, {"ok": True})
    assert asked_before(stand_in, "POST", "/_/render") == ["GET /_/health"]
    assert [p for _, m, p in stand_in.log if m == "POST"] == ["/_/render"]


@HOW_A_HUB_ENDS_A_CONNECTION
def test_a_hub_that_ends_every_connection_after_its_proof_is_silent_and_is_sent_nothing(work, monkeypatch, ends):
    stand_in = StandInHub()
    stand_in.at_proof = lambda n: ends
    wait_for_the_fin(monkeypatch, stand_in)
    with pytest.raises(client.HubSilent):
        client.HubClient(paths.ensure_key(), stand_in.port).call("POST", "/_/render", {"path": "x"})
    assert stand_in.proofs == 2 and stand_in.headers == []


def test_a_hub_that_ended_two_connections_after_its_proof_says_it_proved_itself_and_nothing_was_sent(work):
    """HubSilent says "did not answer", which is true of a proof that got none and not of this: the hub
    proved itself, twice, and nothing was sent. Still a HubSilent, which every command already stops at."""
    stand_in = StandInHub()
    stand_in.at_proof = lambda n: True
    with pytest.raises(client.HubSilent) as e:
        client.HubClient(paths.ensure_key(), stand_in.port).call("POST", "/_/render", {"path": "x"})
    said_so = str(e.value)
    assert f"the sheaf hub on 127.0.0.1:{stand_in.port} proved itself" in said_so
    assert "nothing was sent" in said_so and "sheaf restart" in said_so and "did not answer" not in said_so


@HOW_A_HUB_ENDS_A_CONNECTION
def test_the_door_whose_hub_ends_two_connections_after_its_proof_says_it_proved_itself(
        work, monkeypatch, ends):
    """The door's two tries end the way a command's two do: the hub proved itself and ended the
    connection each time, so nothing was sent, and the agent is told that, not "not reachable"."""
    stand_in = StandInHub()
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    link = client.DoorLink("Claude", say=lambda s: None)
    assert said(link, rpc("ping"))[0] == 200
    proofs_so_far = stand_in.proofs
    stand_in.at_proof = lambda n: ends if n > proofs_so_far else False
    wait_for_the_fin(monkeypatch, stand_in)
    with pytest.raises(client.HubUnavailable) as e:
        said(link, rpc("ping", id=2))
    said_so = str(e.value)
    assert f"the sheaf hub on 127.0.0.1:{stand_in.port} proved itself" in said_so
    assert "nothing was sent" in said_so and "sheaf restart" in said_so and "not reachable" not in said_so
    assert len(stand_in.connections_that_carried_a_message()) == 1       # only the first ping was ever sent


def test_a_command_whose_hub_ends_two_connections_after_its_proof_says_it_proved_itself(sheaf, monkeypatch):
    stand_in = StandInHub()
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    stand_in.at_proof = lambda n: n >= 2                         # the challenge passes; the call's two proofs end
    r = sheaf("list")
    assert r.code == 1
    assert f"  ! the sheaf hub on 127.0.0.1:{stand_in.port} proved itself" in r.err and "did not answer" not in r.err
    assert stand_in.headers == []


def test_the_doors_version_check_asks_for_the_jobs_on_the_connection_that_proved_the_hub(work, monkeypatch):
    """A hub that runs an older version: the door looks at its jobs before it decides to stop it."""
    stand_in = StandInHub(version="0.0.1")
    stand_in.answers["/_/jobs"] = {"ok": True, "asking": ["a"], "telling": []}
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    said_out = []
    link = client.DoorLink("Claude", say=said_out.append)
    assert said(link, rpc("ping"))[0] == 200
    assert asked_before(stand_in, "GET", "/_/jobs") == ["GET /_/health"]
    assert any("an Ask or Tell is running" in line for line in said_out)
    assert stand_in.headers[0]["X-Sheaf-Key"] == key_of_the_test()


def test_a_hub_that_a_stranger_replaces_after_the_doors_first_proof_is_not_sent_the_jobs_request(work, monkeypatch):
    stand_in = StandInHub(version="0.0.1")
    stand_in.at_proof, held = swapping_at(stand_in)
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    link = client.DoorLink("Claude", say=lambda s: None)
    with pytest.raises(client.HubUnavailable, match="something else holds"):
        link.post(json.dumps(rpc("ping")).encode())
    s, seen = held[0]
    s.close()
    assert only_proofs(seen)
    assert stand_in.headers == []


def test_a_hub_that_a_stranger_replaces_after_the_jobs_request_is_not_sent_the_stop(work, monkeypatch):
    """The door that finds an older, idle hub stops it for the upgrade: that request proves first too."""
    monkeypatch.setattr(client, "STOP_WAIT", 0.3)
    stand_in = StandInHub(version="0.0.1")
    stand_in.at_proof, held = swapping_at(stand_in, 2)           # the proof of the jobs request
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    link = client.DoorLink("Claude", say=lambda s: None)
    with pytest.raises(client.HubUnavailable, match="something else holds"):
        link.post(json.dumps(rpc("ping")).encode())
    s, seen = held[0]
    s.close()
    assert only_proofs(seen)
    assert [(m, p) for _, m, p in stand_in.log if m != "GET" or p != "/_/health"] == [("GET", "/_/jobs")]


def sheaf_open_a_document(sheaf, work, monkeypatch, stand_in):
    """`sheaf open` of a document against the stand-in hub; what the browser was given."""
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    opened = []
    monkeypatch.setattr("sheafmd.cli.webbrowser.open", lambda url, *a, **k: opened.append(url) or True)
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    stand_in.answers.setdefault("/_/render", {"ok": True, "doc": "work/plan.md", "tabs": 0,
                                              "url": f"http://127.0.0.1:{stand_in.port}/work/plan.md"})
    stand_in.answers.setdefault("/_/signin", {"ok": True, "nonce": "N" * 43, "expires": 30})
    return sheaf("open", f), opened


def test_sheaf_open_asks_each_of_its_requests_on_a_connection_that_proved_the_hub(
        sheaf, work, monkeypatch):
    stand_in = StandInHub()
    r, opened = sheaf_open_a_document(sheaf, work, monkeypatch, stand_in)
    assert r.code == 0, r.err
    assert asked_before(stand_in, "POST", "/_/render") == ["GET /_/health"]
    assert asked_before(stand_in, "POST", "/_/signin") == ["GET /_/health"]
    assert len(opened) == 1


@pytest.mark.parametrize("at, then_sent", [(1, []), (2, ["/_/render"])])
def test_sheaf_open_on_a_hub_that_a_stranger_replaces_stops_and_the_stranger_is_sent_nothing(
        sheaf, work, monkeypatch, at, then_sent):
    """After the first proof (`ensure_hub`) the render's own proof is asked of the stranger; after the
    render's, the sign-in's is: whichever request comes next proves the hub first."""
    stand_in = StandInHub()
    stand_in.at_proof, held = swapping_at(stand_in, at)
    r, opened = sheaf_open_a_document(sheaf, work, monkeypatch, stand_in)
    s, seen = held[0]
    s.close()
    assert r.code == 1 and f"  ! something else holds 127.0.0.1:{stand_in.port}" in r.err
    assert only_proofs(seen) and opened == []
    assert [p for _, m, p in stand_in.log if p != "/_/health"] == then_sent


def test_sheaf_open_sends_the_sign_in_on_the_connection_that_proved_the_hub_even_if_it_is_replaced_then(
        sheaf, work, monkeypatch):
    stand_in = StandInHub()
    stand_in.at_proof, held = swapping_at(stand_in, 3)           # the proof of the sign-in request
    r, opened = sheaf_open_a_document(sheaf, work, monkeypatch, stand_in)
    s, seen = held[0]
    s.close()
    assert r.code == 0, r.err
    assert seen == [] and len(opened) == 1


def test_sheaf_open_on_a_hub_that_does_not_answer_the_proof_of_the_sign_in_says_so_and_sends_nothing(
        sheaf, work, monkeypatch):
    stand_in = StandInHub()
    stand_in.at_proof = lambda n: "silent" if n == 3 else False
    r, opened = sheaf_open_a_document(sheaf, work, monkeypatch, stand_in)
    assert r.code == 1
    assert f"  ! the sheaf hub on 127.0.0.1:{stand_in.port} did not answer" in r.err and "something else" not in r.err
    assert opened == [] and [p for _, m, p in stand_in.log if p != "/_/health"] == ["/_/render"]


@pytest.mark.parametrize("how", ["close", "hold"])
def test_sheaf_open_whose_sign_in_request_loses_the_hub_after_its_proof_exits_1_and_opens_no_browser(
        sheaf, work, monkeypatch, how):
    """Not a refusal of the link: the hub proved itself and then the request got no answer, which is
    what a failed proof is too (SPEC 9.4). The URL is printed, as it is when the proof fails."""
    monkeypatch.setattr(client, "TIMEOUT", 0.3)
    stand_in = StandInHub()
    stand_in.on_request["/_/signin"] = how
    r, opened = sheaf_open_a_document(sheaf, work, monkeypatch, stand_in)
    assert r.code == 1
    assert f"  ! the sheaf hub on 127.0.0.1:{stand_in.port}" in r.err and "may have been applied" in r.err
    assert "the browser was not opened" not in r.err
    assert opened == [] and r.out.splitlines()[-1] == f"  ~ http://127.0.0.1:{stand_in.port}/work/plan.md"


def test_sheaf_open_on_a_hub_that_refuses_the_sign_in_link_prints_the_advice_and_exits_0(
        sheaf, work, monkeypatch):
    """What the hub says about the link is not what happened to the request: an older hub with no such
    route, or one that will not make a link, leaves the person the command that prints it."""
    stand_in = StandInHub()
    stand_in.answers["/_/signin"] = {"ok": False, "error": "no such route"}
    r, opened = sheaf_open_a_document(sheaf, work, monkeypatch, stand_in)
    assert r.code == 0 and opened == []
    assert "the browser was not opened" in r.err and "no such route" in r.err and "sheaf signin-url" in r.err


@pytest.mark.parametrize("argv", [("stop",), ("list",), ("rotate",), ("roots", "forget", "work"), ("restart",)])
@pytest.mark.parametrize("how", ["stranger", "silent"])
def test_a_command_that_challenges_and_then_calls_stops_when_the_hub_is_not_the_one_that_answers_the_call(
        sheaf, monkeypatch, argv, how):
    """The challenge passed; the call asks for a proof of its own, and a hub that is gone, or that
    answers nothing, is met with the exit and the message of any other failed proof."""
    stand_in = StandInHub()
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    if how == "stranger":
        stand_in.at_proof, held = swapping_at(stand_in)
    else:
        stand_in.at_proof = lambda n: "silent" if n >= 2 else False
    r = sheaf(*argv)
    assert r.code == 1
    if how == "stranger":
        s, seen = held[0]
        s.close()
        assert f"  ! something else holds 127.0.0.1:{stand_in.port}" in r.err
        assert only_proofs(seen)
    else:
        assert f"  ! the sheaf hub on 127.0.0.1:{stand_in.port} did not answer" in r.err
    assert [p for _, m, p in stand_in.log if p != "/_/health"] == []
    assert key_of_the_test() not in r.out + r.err


def test_a_restart_through_the_service_does_not_tell_a_hub_that_a_stranger_replaced_that_it_is_restarting(
        sheaf, monkeypatch):
    """`/_/restarting` carries the key too: the hub the service runs proves itself again for it, and
    when it cannot the service is not asked to restart anything."""
    stand_in, controlled = StandInHub(service=True), []
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    monkeypatch.setattr("sheafmd.lifecycle.service.installed", lambda: True)
    monkeypatch.setattr("sheafmd.lifecycle.service.control", controlled.append)
    stand_in.at_proof, held = swapping_at(stand_in)
    r = sheaf("restart")
    s, seen = held[0]
    s.close()
    assert r.code == 1 and f"  ! something else holds 127.0.0.1:{stand_in.port}" in r.err
    assert only_proofs(seen) and controlled == [] and stand_in.headers == []


@pytest.mark.parametrize("hub", ["older", "gone"])
def test_a_restart_the_manager_refused_says_what_the_manager_said_whatever_the_hub_answers_after(
        sheaf, monkeypatch, hub):
    """The command takes back what it told the hub. A hub of the version before has no such route,
    and a hub may be gone by then: the person still reads the manager's words, and only those."""
    stand_in = StandInHub(service=True)
    if hub == "gone":
        stand_in.on_request[("DELETE", "/_/restarting")] = "close"
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    monkeypatch.setattr("sheafmd.lifecycle.service.installed", lambda: True)

    def refused(verb):
        raise ServiceError("`systemctl --user restart sheaf.service` failed (1): "
                           "Failed to connect to bus")
    monkeypatch.setattr("sheafmd.lifecycle.service.control", refused)
    r = sheaf("restart")
    assert r.code == 1 and r.out == ""
    assert r.err == ("sheaf: `systemctl --user restart sheaf.service` failed (1): "
                     "Failed to connect to bus\n")
    asked = [(m, p) for _, m, p in stand_in.log if p != "/_/health"]
    assert asked == [("POST", "/_/restarting"), ("DELETE", "/_/restarting")]


# ── a request that loses the hub after its proof ─────────────────────────────

@pytest.mark.parametrize("how", ["close", "hold"])
def test_a_commands_request_that_loses_the_hub_after_its_proof_says_it_may_have_been_applied(work, monkeypatch, how):
    monkeypatch.setattr(client, "TIMEOUT", 0.3)
    stand_in = StandInHub()
    stand_in.on_request["/_/render"] = how
    with pytest.raises(client.Impostor) as e:                    # what every command already stops at
        client.HubClient(paths.ensure_key(), stand_in.port).call("POST", "/_/render", {"path": "x"})
    assert f"the sheaf hub on 127.0.0.1:{stand_in.port}" in str(e.value)
    assert "may have been applied" in str(e.value) and "something else" not in str(e.value)
    assert [p for _, m, p in stand_in.log if m == "POST"] == ["/_/render"]       # it went once, and is not sent again


@pytest.mark.parametrize("argv, path", [(("stop",), "/_/stop"), (("list",), "/_/index.json"),
                                        (("rotate",), "/_/rotate"), (("roots", "forget", "work"), "/_/forget"),
                                        (("restart",), "/_/stop")])
def test_a_command_whose_request_loses_the_hub_after_its_proof_says_so_and_exits_1(
        sheaf, monkeypatch, argv, path):
    stand_in = StandInHub()
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    stand_in.on_request[path] = "close"
    r = sheaf(*argv)
    assert r.code == 1
    assert f"  ! the sheaf hub on 127.0.0.1:{stand_in.port}" in r.err and "may have been applied" in r.err
    assert [p for _, m, p in stand_in.log if p == path] == [path]               # the request went once
    assert key_of_the_test() not in r.out + r.err


def test_a_command_whose_hub_is_gone_between_its_challenge_and_its_request_says_nothing_was_sent(
        sheaf, monkeypatch):
    stand_in = StandInHub()
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    stand_in.at_proof = lambda n: stand_in.lose_the_port() if n == 1 else False      # no one takes the port
    r = sheaf("list")
    assert r.code == 1
    assert f"  ! the sheaf hub on 127.0.0.1:{stand_in.port}" in r.err and "nothing was sent" in r.err
    assert "may have been applied" not in r.err and stand_in.headers == []


def test_a_door_whose_version_check_loses_the_hub_fails_the_message_clearly_and_stays_up(work, monkeypatch):
    """The older hub's jobs are asked on the proof's connection (`_meet_version`); losing it there used to
    end the door with a traceback."""
    stand_in = StandInHub(version="0.0.1")
    stand_in.answers["/_/jobs"] = {"ok": True, "asking": ["a"], "telling": []}      # a job runs: no upgrade stop
    stand_in.on_request["/_/jobs"] = "close"
    monkeypatch.setenv("SHEAF_PORT", str(stand_in.port))
    link = client.DoorLink("Claude", say=lambda s: None)
    with pytest.raises(client.HubUnavailable, match="before any message of yours was sent") as e:
        link.post(json.dumps(rpc("ping")).encode())
    assert "may have been applied" not in str(e.value)           # the agent's message was never sent
    stand_in.on_request.clear()
    assert said(link, rpc("ping", id=2))[1]["id"] == 2


# ── the command, as a process that starts its own hub ────────────────────────

def sheaf_mcp(data, *args, env=None):
    return subprocess.run([sys.executable, "-m", "sheafmd", "mcp", *args], input=data,
                          capture_output=True, timeout=120, env={**os.environ, **(env or {})})


def test_the_command_starts_the_hub_and_answers_the_whole_conversation(work):
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    comment(f)
    comment(f, "First paragraph", "And apples?")
    Roots().for_document(f)                     # the hub the command starts reads roots.json
    ask = {"doc": str(f), "id": "c1"}
    p = sheaf_mcp(lines(
        rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                           "clientInfo": {"name": "t", "version": "0"}}),
        rpc("notifications/initialized", id=None),
        rpc("tools/list", id=2),
        rpc("tools/call", {"name": "threads", "arguments": {"doc": str(f)}}, id=3),
        rpc("tools/call", {"name": "documents", "arguments": {}}, id=4),
        rpc("tools/call", {"name": "reply", "arguments": {**ask, "text": "Done.", "role": "action",
                                                          "resolve": True}}, id=5),
        rpc("tools/call", {"name": "resolve", "arguments": {"doc": str(f), "id": "c2"}}, id=6),
        rpc("tools/call", {"name": "threads", "arguments": {"doc": str(f), "status": "all"}}, id=7),
        rpc("tools/call", {"name": "documents", "arguments": {}}, id=8),
    ), "--agent", "codex")
    assert p.returncode == 0, p.stderr
    got = [json.loads(x) for x in p.stdout.splitlines()]
    assert [g["id"] for g in got] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert got[0]["result"]["serverInfo"]["name"] == "sheaf"
    assert {t["name"] for t in got[1]["result"]["tools"]} == {"documents", "threads", "reply", "resolve",
                                                             "read", "create", "update"}
    assert all(g["result"]["isError"] is False for g in got[2:])

    def said(i):
        return json.loads(got[i]["result"]["content"][0]["text"])

    assert {c["id"] for c in said(2)["comments"]} == {"c1", "c2"}
    [row] = said(3)
    assert (row["doc"], row["open"], row["path"]) == ("work/plan.md", 2, str(f))
    assert said(5) == {"id": "c2", "status": "resolved"}
    c1 = next(c for c in said(6)["comments"] if c["id"] == "c1")
    assert c1["replies"][0]["display"] == "Codex"
    assert said(7) == []                                         # nothing is open any more
    t = rdc.parse(f.read_text(encoding="utf-8"))
    r = t.by_id("c1")
    assert r.status == "resolved" and (r.replies[-1].by, r.replies[-1].role) == ("Codex", "action")
    assert t.by_id("c2").status == "resolved"
    assert paths.key_file().read_text(encoding="ascii").strip().encode() not in p.stdout


def test_the_command_makes_reads_and_changes_a_page(work):
    """`read`, `create` and `update` over stdio, with the key: a hash is the text's own, so the
    whole conversation can be written before it is sent."""
    (work / "plan.md").write_text(PLAN, encoding="utf-8")
    Roots().for_document(work / "plan.md")
    page, changed = "# A page\n\nIts text.\n", "# A page\n\nIts new text.\n"

    def call(name, i, **args):
        return rpc("tools/call", {"name": name, "arguments": args}, id=i)
    p = sheaf_mcp(lines(
        call("create", 1, doc="work/new.md", text=page),
        call("read", 2, doc=str(work / "new.md")),
        call("update", 3, doc="work/new.md", text=changed, expected_hash=md_hash(page)),
        call("update", 4, doc="work/new.md", text=page, expected_hash=md_hash(page)),
        call("read", 5, doc="work/new.md", comments=False),
    ), "--agent", "codex")
    assert p.returncode == 0, p.stderr
    got = [json.loads(x)["result"] for x in p.stdout.splitlines()]
    assert [g["isError"] for g in got] == [False, False, False, True, False]
    said = [g["content"][0]["text"] for g in got]
    assert json.loads(said[0])["hash"] == md_hash(page) and json.loads(said[1])["text"] == page
    assert json.loads(said[2])["changed"] is True and "read it again" in said[3]
    assert json.loads(said[4])["text"] == changed == (work / "new.md").read_text(encoding="utf-8")


def test_the_command_signs_with_the_agent_it_finds_around_it(work):
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    comment(f)
    p = sheaf_mcp(lines(rpc("tools/call", {"name": "reply", "arguments": {
        "doc": str(f), "id": "c1", "text": "Hi."}})), env={"CLAUDE_CODE_SESSION_ID": "abc"})
    assert p.returncode == 0, p.stderr
    assert rdc.parse(f.read_text(encoding="utf-8")).by_id("c1").replies[-1].by == "Claude"


def test_the_command_ends_with_its_input(work):
    p = sheaf_mcp(b"")
    assert p.returncode == 0 and p.stdout == b""


def test_a_door_to_a_hub_that_a_stranger_holds_says_why_to_every_request(work):
    s, _ = stranger()
    port = s.getsockname()[1]
    p = sheaf_mcp(lines(rpc("initialize", id=1)), env={"SHEAF_PORT": str(port)})
    s.close()
    got = [json.loads(x) for x in p.stdout.splitlines()]
    assert p.returncode == 0 and got[0]["error"]["code"] == -32603
    assert "something else holds" in got[0]["error"]["message"]
    assert "something else holds" in p.stderr.decode()


def test_a_door_whose_start_up_version_check_loses_the_hub_stays_up_and_says_why_to_each_request(work):
    """`sheaf mcp` against a hub of an older version that closes on the request for its jobs: the
    start-up check is not the end of the door."""
    stand_in = StandInHub(version="0.0.1")
    stand_in.answers["/_/jobs"] = {"ok": True, "asking": ["a"], "telling": []}
    stand_in.on_request["/_/jobs"] = "close"
    p = sheaf_mcp(lines(rpc("initialize", id=1)), env={"SHEAF_PORT": str(stand_in.port)})
    got = [json.loads(x) for x in p.stdout.splitlines()]
    assert p.returncode == 0, p.stderr.decode()
    assert got[0]["id"] == 1 and got[0]["error"]["code"] == -32603
    assert "before any message of yours was sent" in got[0]["error"]["message"]
    assert "may have been applied" not in got[0]["error"]["message"]
    assert "before any message of yours was sent" in p.stderr.decode() and "Traceback" not in p.stderr.decode()


def test_display_for_looks_the_agent_up_by_its_cleaned_name():
    assert mcp.display_for("cod\u200bex", environ={}) == "Codex"
