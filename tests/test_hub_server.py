"""The hub's socket: the handler's answers as real HTTP bytes, the event stream, the watcher,
a clean stop. The hub runs on a thread of this process; the routes themselves are tested in
memory in test_hub_handler.py and test_hub_security.py."""
import http.client
import json
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from importlib.resources import files

import pytest

from helpers import PLAN, comment, read_events, rpc, wait_until_refused
from sheafmd import diagnostics, paths
from sheafmd.hub import server
from sheafmd.hub.core import Hub
from sheafmd.hub.state import Tokens
from sheafmd.source import md_hash, update_file


@pytest.fixture
def live(work):
    """A running hub on a free port: (hub, port, plan file, connect())."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    conns = []

    def connect():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        conns.append(c)
        return c
    yield hub, port, f, connect
    for c in conns:
        c.close()
    srv.close()


def cookie(hub):
    return {"Cookie": f"{hub.auth.cookie_name}={hub.auth.cookie_value()}"}


def get(connect, path, headers=None):
    c = connect()
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    return r, r.read()


def test_a_page_is_served_over_a_real_socket(live):
    hub, port, f, connect = live
    r, body = get(connect, "/work/plan.md", cookie(hub))
    assert r.status == 200 and b"about apples" in body
    assert r.getheader("Content-Security-Policy").startswith("default-src 'none'")
    assert r.getheader("Server") == "sheaf"
    assert int(r.getheader("Content-Length")) == len(body)


def test_the_sign_in_swaps_the_key_for_a_cookie_that_then_works(live):
    hub, port, f, connect = live
    r, _ = get(connect, f"/_/open?key={hub.auth.key}&next=/work/plan.md")
    assert r.status == 303 and r.getheader("Location") == "/work/plan.md"
    jar = r.getheader("Set-Cookie").split(";")[0]
    r, body = get(connect, "/work/plan.md", {"Cookie": jar})
    assert r.status == 200 and hub.auth.key.encode() not in body


def test_a_post_with_the_cookie_and_its_origin_saves(live):
    hub, port, f, connect = live
    text = f.read_text(encoding="utf-8")
    from sheafmd.blocks import split_md_blocks
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    c = connect()
    body = json.dumps({"doc": "work/plan.md", "hash": md_hash(text),
                       "edits": [{"i": i, "html": "<p>Second, over HTTP.</p>"}]})
    c.request("POST", "/_/save", body, {**cookie(hub), "Origin": f"http://127.0.0.1:{port}",
                                        "Content-Type": "application/json"})
    r = c.getresponse()
    assert r.status == 200 and json.loads(r.read())["changed"]
    assert "Second, over HTTP." in f.read_text(encoding="utf-8")


def test_a_post_without_its_origin_is_refused_over_the_wire_too(live):
    hub, port, f, connect = live
    c = connect()
    c.request("POST", "/_/seen", json.dumps({"doc": "work/plan.md", "id": "c1", "count": 1}), cookie(hub))
    assert c.getresponse().status == 403


def test_a_connection_is_kept_for_the_next_request(live):
    hub, port, f, connect = live
    c = connect()
    for _ in range(3):
        c.request("GET", "/_/health")
        r = c.getresponse()
        assert r.status == 200
        r.read()


def test_a_wrong_host_header_is_403_over_the_wire(live):
    hub, port, f, connect = live
    c = connect()
    c.putrequest("GET", "/_/health", skip_host=True)
    c.putheader("Host", "evil.example")
    c.endheaders()
    assert c.getresponse().status == 403


def test_a_request_the_server_itself_cannot_parse_gets_json_not_an_html_page(live):
    hub, port, f, connect = live
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET / HTTP/9.9\r\nHost: 127.0.0.1\r\n\r\n")
    data = b""
    while chunk := s.recv(4096):
        data += chunk
    s.close()
    # http.server answers an HTTP version it does not know the way HTTP/0.9 did, with no header
    # lines at all: what matters is that no HTML page comes out, since that one carries no policy.
    assert b"<" not in data and json.loads(data[data.index(b"{"):])["ok"] is False


def test_a_body_over_the_limit_is_refused_without_reading_it(live):
    hub, port, f, connect = live
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(f"POST /_/save HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
              f"Cookie: {hub.auth.cookie_name}={hub.auth.cookie_value()}\r\n"
              f"Content-Length: {50 * 1024 * 1024}\r\n\r\n".encode())
    assert s.recv(4096).startswith(b"HTTP/1.1 413")
    s.close()


def _answer(port, head: bytes, body: bytes = b"", wait=20):
    """Send a request head that promises a body and `body` of it; the status line of the answer,
    or None when nothing came back in `wait` seconds. A hub that wrongly waits for the body it was
    promised holds the request for BODY_SECONDS (30), so any `wait` under that tells it from one
    that refuses first; 20 leaves a process that is not scheduled for a few seconds (a loaded
    machine) room to answer."""
    s = socket.create_connection(("127.0.0.1", port), timeout=wait)
    try:
        s.sendall(head + body)
        return s.recv(4096).split(b"\r\n")[0]
    except socket.timeout:
        return None
    finally:
        s.close()


@pytest.mark.parametrize("path,extra", [
    ("/_/save", ""),                                   # no cookie: not signed in
    ("/_/mcp", ""),                                    # no key, no token
    ("/_/mcp", "Authorization: Bearer sheaf_notatoken\r\n"),
    ("/_/render", "Cookie: {cookie}\r\n"),             # a cookie on a route that needs the key
    ("/_/save", "Cookie: {cookie}\r\n"),               # a cookie without its Origin
])
def test_a_body_is_not_read_for_a_caller_who_is_refused(live, path, extra):
    """The refusal comes before the body, so a local user who cannot sign in cannot hold a thread
    open by promising a body and never sending it (SPEC 9: the checks come first)."""
    hub, port, f, connect = live
    extra = extra.format(cookie=f"{hub.auth.cookie_name}={hub.auth.cookie_value()}")
    head = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n{extra}"
            f"Content-Length: 4096\r\n\r\n").encode()
    line = _answer(port, head)
    assert line is not None and line.split()[1] in (b"401", b"403")


@pytest.mark.parametrize("method,path,host,origin,status", [
    ("POST", "/_/save", "evil.example", True, b"403"),            # a signed-in caller on a wrong Host
    ("POST", "/_/save", None, "http://evil.example", b"403"),     # a cookie with another site's Origin
    ("POST", "/_/nonesuch", None, True, b"404"),                  # a route that does not exist
    ("POST", "/_/live", None, True, b"405"),                      # a route that does not take a POST
])
def test_a_body_is_not_read_for_a_request_the_hub_refuses_for_any_reason(live, method, path, host, origin, status):
    """Whatever refuses the request (the Host, the Origin, no such route, the wrong method), it
    does so before the body it promised: nothing is sent after the head, and the answer comes."""
    hub, port, f, connect = live
    origin = f"http://127.0.0.1:{port}" if origin is True else origin
    head = (f"{method} {path} HTTP/1.1\r\nHost: {host or '127.0.0.1:%d' % port}\r\n"
            f"Origin: {origin}\r\nCookie: {hub.auth.cookie_name}={hub.auth.cookie_value()}\r\n"
            f"Content-Length: 4096\r\n\r\n").encode()
    line = _answer(port, head)
    assert line is not None and line.split()[1] == status


def test_a_refused_request_with_a_body_still_gets_its_answer_and_the_connection_ends(live):
    hub, port, f, connect = live
    body = b"x" * 70000
    head = (f"POST /_/save HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            f"Content-Length: {len(body)}\r\n\r\n").encode()
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(head + body)
    data = b""
    while chunk := s.recv(4096):
        data += chunk
    s.close()
    assert data.startswith(b"HTTP/1.1 401") and b"Connection: close" in data


def _everything_the_hub_says(port, request: bytes, wait=20):
    s = socket.create_connection(("127.0.0.1", port), timeout=wait)
    s.sendall(request)
    data = b""
    try:
        while chunk := s.recv(4096):
            data += chunk
    except socket.timeout:
        data += b"[the connection stayed open]"
    finally:
        s.close()
    return data


def test_a_refused_chunked_request_ends_the_connection_and_what_follows_is_not_read_as_a_request(live):
    """The hub takes a body by its Content-Length only. A request that sends its body in chunks
    has none it can skip over, so what follows its head must not be read as the next request."""
    hub, port, f, connect = live
    smuggled = f"GET /_/nonesuch HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n"
    request = (f"POST /_/save HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nTransfer-Encoding: chunked\r\n\r\n"
               f"{len(smuggled):x}\r\n{smuggled}\r\n0\r\n\r\n").encode()
    data = _everything_the_hub_says(port, request)
    assert data.startswith(b"HTTP/1.1 401") and b"Connection: close" in data
    assert data.count(b"HTTP/1.1 ") == 1 and b"[the connection stayed open]" not in data


def test_a_signed_in_chunked_request_also_ends_the_connection(live):
    hub, port, f, connect = live
    smuggled = f"GET /_/nonesuch HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n"
    request = (f"POST /_/seen HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
               f"Cookie: {hub.auth.cookie_name}={hub.auth.cookie_value()}\r\nTransfer-Encoding: chunked\r\n\r\n"
               f"{len(smuggled):x}\r\n{smuggled}\r\n0\r\n\r\n").encode()
    data = _everything_the_hub_says(port, request)
    assert data.count(b"HTTP/1.1 ") == 1 and b"Connection: close" in data
    assert b"[the connection stayed open]" not in data


def test_a_body_that_stops_arriving_is_given_up_on(live, monkeypatch):
    """A signed-in caller that sends part of a body and stalls holds its thread for the deadline,
    not for ever."""
    hub, port, f, connect = live
    monkeypatch.setattr(server, "BODY_SECONDS", 0.5, raising=False)
    head = (f"POST /_/seen HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
            f"Cookie: {hub.auth.cookie_name}={hub.auth.cookie_value()}\r\n"
            f"Content-Length: 100\r\n\r\n").encode()
    line = _answer(port, head, b'{"doc"')
    assert line is not None and line.split()[1] == b"408"


def test_a_body_that_trickles_in_is_given_up_on_at_the_deadline_not_at_each_byte(live, monkeypatch):
    hub, port, f, connect = live
    monkeypatch.setattr(server, "BODY_SECONDS", 0.6, raising=False)
    head = (f"POST /_/seen HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
            f"Cookie: {hub.auth.cookie_name}={hub.auth.cookie_value()}\r\n"
            f"Content-Length: 100\r\n\r\n").encode()
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(head)
    began = time.time()
    try:
        for _ in range(40):                  # a byte every 0.1 s keeps every single read alive
            s.sendall(b" ")
            time.sleep(0.1)
            s.setblocking(False)
            try:
                if s.recv(1, socket.MSG_PEEK):
                    break
            except BlockingIOError:
                pass
            finally:
                s.setblocking(True)
        s.settimeout(3)
        assert s.recv(4096).startswith(b"HTTP/1.1 408")
    finally:
        s.close()
    assert time.time() - began < 3


def test_a_connection_that_says_nothing_is_closed(live, monkeypatch):
    """No socket timeout meant a client could hold a thread by connecting and sending nothing."""
    hub, port, f, connect = live
    monkeypatch.setattr(server, "IDLE_SECONDS", 0.5, raising=False)
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    try:
        assert s.recv(10) == b""             # the hub hung up; a timeout here means it did not
    finally:
        s.close()


# ── the stream ───────────────────────────────────────────────────────────────

def test_a_stream_says_retry_then_hello_then_what_changes_on_disk(live):
    hub, port, f, connect = live
    c = connect()
    c.request("GET", "/_/live?doc=work/plan.md", headers=cookie(hub))
    r = c.getresponse()
    assert r.status == 200 and r.getheader("Content-Type") == "text/event-stream"
    assert r.fp.readline() == b"retry: 2000\n"
    assert r.fp.readline() == b"\n"
    (hello,) = read_events(r, 1)
    assert hello[0] == "hello" and hello[1]["tabs"] == 1 and hello[1]["boot"] == hub.boot
    update_file(f, lambda t: t.replace("about apples", "about apples and plums"))
    (changed,) = read_events(r, 1)                     # the watcher thread runs once a second
    assert changed[0] == "changed" and changed[1]["textSame"] is False
    assert changed[1]["hash"] == md_hash(f.read_text(encoding="utf-8"))


def test_a_save_and_a_comment_each_reach_an_open_tab_as_one_changed_event(no_watcher, live):
    """SPEC 7.3 over real sockets: the tab that did not write hears of a write made through the
    hub, once. The watcher is quiet here (and ticked by hand), so what arrives is the hub's own
    telling, and a duplicate from the watcher would sit between the two events."""
    from sheafmd.blocks import split_md_blocks
    import sheafmd.comments as rdc
    hub, port, f, connect = live
    tab = connect()
    tab.request("GET", "/_/live?doc=work/plan.md", headers=cookie(hub))
    stream = tab.getresponse()
    assert read_events(stream, 1)[0][0] == "hello"

    def post(path, body):
        c = connect()
        c.request("POST", path, json.dumps({"doc": "work/plan.md", **body}),
                  {**cookie(hub), "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"})
        return json.loads(c.getresponse().read())

    text = f.read_text(encoding="utf-8")
    i = next(i for i, b in enumerate(split_md_blocks(text)) if b.content.startswith("Second"))
    saved = post("/_/save", {"hash": md_hash(text), "edits": [{"i": i, "html": "<p>Second, saved.</p>"}]})
    hub.tick()
    text2 = f.read_text(encoding="utf-8")
    blk, s, e = rdc.find_quote(text2, "First paragraph")
    commented = post("/_/comment", {"op": "add", "hash": md_hash(text2), "block": blk, "start": s,
                                    "end": e, "quote": "First paragraph", "body": "Why?"})
    hub.tick()
    got = read_events(stream, 2, timeout=5)
    assert [n for n, _ in got] == ["changed", "changed"]
    assert [d["hash"] for _, d in got] == [saved["hash"], commented["hash"]]
    assert got[0][1]["base"] == md_hash(text) and got[1][1]["base"] == saved["hash"]
    assert got[0][1]["textSame"] is False and got[1][1]["textSame"] is True
    assert got[1][1]["comments"][0]["body"] == "Why?"


# The page's side of the same event (SPEC 7.3). The tab that wrote hears its own `changed`, and
# may hear it before the answer to its request, while it still holds the old hash. Run under
# node when it is installed, like test_page_toast.py: the page's functions are read out of the
# asset and run against stubs, nothing here drives a browser.

JS = (files("sheafmd") / "page" / "page.js").read_text(encoding="utf-8")


def js_function(name):
    m = re.search(rf"^  (?:async )?function {name}\(.*?^  }}\n", JS, re.S | re.M)
    return m.group(0) if m else ""


def js_line(start):
    m = re.search(rf"^  {re.escape(start)}.*$", JS, re.M)
    assert m, f"page.js has no line that starts {start!r}"
    return m.group(0)


def changed_listener():
    m = re.search(r"live\.addEventListener\('changed', (function \(ev\) \{.*?^      \})\);", JS, re.S | re.M)
    assert m, "page.js has no listener for the changed event"
    return m.group(1)


PAGE_STUBS = """
var CFG = { doc: 'work/plan.md' }, hash = 'H0', popId = 'c7', anchors = {};
var settled = [], applied = [], pending = [];
function applyComments(d) {
  if ((d.comments || []).some(function (c) { return !anchors[c.id]; })) return false;
  applied.push(d.hash); if (d.hash) hash = d.hash; return true;
}
function settle(id) { settled.push(id); }
var autosaveOwed = false;                           // post() pays an owed autosave after an answer
function payOwed() {}
function reloadWhenFree(id) { settle(id); }
globalThis.fetch = function () {
  return new Promise(function (resolve) {
    pending.push(function (j, ok) {
      resolve({ ok: ok !== false, status: ok === false ? 409 : 200, json: async function () { return j; } });
    });
  });
};
"""

PAGE_SCENARIOS = """
var listener = %(listener)s;
function hear(d) { listener({ data: JSON.stringify(d) }); }
function later() { return new Promise(function (r) { setTimeout(r, 5); }); }
function reset() { hash = 'H0'; anchors = {}; settled.length = 0; applied.length = 0; }
async function save() { var j = await post('/_/save', { hash: hash, edits: [] }); hash = j.hash; return j; }
async function add() { var j = await post('/_/comment', { op: 'add' }); anchors[j.id] = true; applyComments(j); return j; }
var own = { hash: 'H1', base: 'H0', textSame: false, comments: [] };
var out = {};
(async function () {
  reset();                                          // a save, its own event before its answer
  var p = save(); hear(own);
  var during = settled.length;
  pending.shift()({ ok: true, hash: 'H1' }); await p; await later();
  out.save_event_first = [during, settled.length, hash];

  reset();                                          // a save, its own event after its answer
  p = save(); pending.shift()({ ok: true, hash: 'H1' }); await p; await later(); hear(own);
  out.save_event_after = [settled.length, hash];

  reset();                                          // a new comment: its anchor is placed after the answer
  p = add();
  hear({ hash: 'H1', base: 'H0', textSame: true, comments: [{ id: 'c1' }] });
  pending.shift()({ ok: true, hash: 'H1', id: 'c1', comments: [{ id: 'c1' }] }); await p; await later();
  out.comment_event_first = [settled.length, applied.slice(), hash];

  reset();                                          // another writer's event behind its own
  p = save(); hear(own); hear({ hash: 'H2', base: 'H1', textSame: false, comments: [] });
  during = settled.length;
  pending.shift()({ ok: true, hash: 'H1' }); await p; await later();
  out.outsider_behind_own = [during, settled.slice(), hash];

  reset();                                          // comments only, behind its own: taken in place
  p = save(); hear(own); hear({ hash: 'H2', base: 'H1', textSame: true, comments: [] });
  pending.shift()({ ok: true, hash: 'H1' }); await p; await later();
  out.comments_behind_own = [settled.length, applied.slice(), hash];

  reset();                                          // no write in flight: heard at once
  hear({ hash: 'H5', base: 'H0', textSame: false, comments: [] });
  out.heard_at_once = [settled.slice(), hash];

  reset();                                          // a request that writes no text holds nothing
  p = post('/_/seen', { id: 'c1', count: 1 }); hear({ hash: 'H5', base: 'H0', textSame: false, comments: [] });
  out.seen_holds_nothing = [settled.slice()];
  pending.shift()({ ok: true }); await p;

  reset();                                          // a save that failed: what was heard is looked at
  p = save().catch(function () {}); hear(own);
  pending.shift()({ ok: false, error: 'no' }, false); await p; await later();
  out.failed_save = [settled.slice(), hash];

  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_a_page_ignores_the_event_of_its_own_write_whichever_reaches_it_first():
    parts = [PAGE_STUBS, js_line("var SAVE_WAIT"), js_line("var WAIT"), js_line("var writes"), js_line("var ownWrites"), js_line("var checkAgain"), js_line("var lastLate"), js_line("function notLate"),
             "function checkText() {}", js_function("post"), js_function("heardAfterCheck"), js_function("heard"), js_function("replayHeld"), PAGE_SCENARIOS % {"listener": changed_listener()}]
    r = subprocess.run(["node", "-e", "\n".join(parts)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {
        "save_event_first": [0, 0, "H1"],            # held, then ignored: it names the hash now held
        "save_event_after": [0, "H1"],
        "comment_event_first": [0, ["H1"], "H1"],    # no reload for a comment the page has yet to place
        "outsider_behind_own": [0, ["c7"], "H1"],    # held too, then told once
        "comments_behind_own": [0, ["H2"], "H2"],
        "heard_at_once": [["c7"], "H0"],
        "seen_holds_nothing": [["c7"]],
        "failed_save": [["c7"], "H0"],
    }


def test_only_the_writes_that_change_the_file_hold_the_events_of_the_page():
    post = js_function("post")
    assert "'/_/save'" in post and "'/_/comment'" in post and "ownWrites" in post
    assert "'/_/seen'" not in post and "'/_/ask'" not in post and "'/_/tell'" not in post
    assert "heard(" in changed_listener()


def test_a_closed_tab_is_counted_out_within_two_seconds(live):
    hub, port, f, connect = live
    c = connect()
    c.request("GET", "/_/live?doc=work/plan.md", headers=cookie(hub))
    r = c.getresponse()
    read_events(r, 1)
    assert hub.tabs("work/plan.md") == 1
    r.close()
    c.close()
    deadline = time.time() + 3
    while hub.tabs("work/plan.md") and time.time() < deadline:
        time.sleep(0.05)
    assert hub.tabs("work/plan.md") == 0


def test_a_stream_whose_root_is_forgotten_is_told_the_document_is_gone_and_ended(live):
    hub, port, f, connect = live
    s = connect()
    s.request("GET", "/_/live?doc=work/plan.md", headers=cookie(hub))
    sock = s.sock                                      # the response takes it over
    r = s.getresponse()
    read_events(r, 1)
    sock.settimeout(3)
    assert hub.forget_root("work").name == "work"
    assert read_events(r, 1) == [("gone", {"doc": "work/plan.md"})]
    assert r.fp.readline() == b""                      # the hub closed it: the tab has nothing to wait for


def test_a_stop_by_key_tells_the_streams_and_ends_the_server(live):
    hub, port, f, connect = live
    s = connect()
    s.request("GET", "/_/live?doc=work/plan.md", headers=cookie(hub))
    r = s.getresponse()
    read_events(r, 1)
    c = connect()
    c.request("POST", "/_/stop", json.dumps({"reason": "stop"}), {"X-Sheaf-Key": hub.auth.key})
    assert json.loads(c.getresponse().read()) == {"ok": True}
    assert read_events(r, 1) == [("hub-stopping", {"reason": "stop"})]
    assert wait_until_refused(port, 2), "the hub still listens after a stop"


def test_close_returns_while_connections_hold_a_request_that_never_ends(work, monkeypatch):
    """`close()` waits for no connection: one that sent nothing and one whose request head never ends
    each hold a handler thread, and the server is closed with both still open. A close that waited for
    them would stand still for as long as the client does, and so would `sheaf stop`."""
    monkeypatch.setattr(server, "IDLE_SECONDS", 3600)          # the connections do not time out meanwhile
    sock = server.bind(0)
    port = sock.getsockname()[1]
    srv = server.HubServer(Hub(port=port, key=paths.ensure_key(), started_by="test"), sock)
    srv.start()
    held = [socket.create_connection(("127.0.0.1", port), timeout=5) for _ in range(2)]
    closing = None
    try:
        held[1].sendall(b"GET /_/health HTTP/1.1\r\nHost: 127.0.0.1\r\n")     # no blank line: the head never ends
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)       # accepted after both, so they are held
        c.request("GET", "/_/health")
        assert c.getresponse().status == 200
        c.close()
        closing = threading.Thread(target=srv.close, daemon=True)
        closing.start()
        closing.join(30)
        assert not closing.is_alive(), "close() did not return while two connections held a request"
    finally:
        for s in held:
            s.close()
        if closing is None:                                 # failed before the close: the server still serves
            srv.close()


def test_a_signal_that_lands_on_another_thread_still_ends_the_wait(work):
    """The kernel may hand a SIGTERM to any thread of the hub. Python runs its handler on the
    main thread, but a main thread blocked on a plain lock is not woken by it: the hub must not
    sit in one (it would ignore its first SIGTERM for 30 s)."""
    sock = server.bind(0)
    hub = Hub(port=sock.getsockname()[1], key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    old = signal.signal(signal.SIGUSR1, lambda *a: srv.done.set())
    other = threading.Thread(target=time.sleep, args=(10,), daemon=True)
    other.start()
    threading.Timer(0.2, signal.pthread_kill, (other.ident, signal.SIGUSR1)).start()
    giveup = threading.Timer(4, srv.done.set)          # so that a hang fails instead of hanging
    giveup.start()
    try:
        began = time.time()
        srv.wait()
        assert time.time() - began < 2
    finally:
        giveup.cancel()
        signal.signal(signal.SIGUSR1, old)
        sock.close()


# ── the door, over the wire ──────────────────────────────────────────────────

@pytest.fixture
def no_watcher(monkeypatch):
    """The watcher tells a tab of any change on disk within a second, on its own. With it
    silent, what a tab hears came from the write the door has just made."""
    monkeypatch.setattr(server, "TICK_SECONDS", 3600)


def test_an_action_reply_through_the_door_ends_a_tell_wait_and_a_tab_hears_it_at_once(no_watcher, live):
    """On real sockets: a token's POST to /_/mcp, an open tab's event stream,
    and a Tell wait on the hub. test_mcp_tools.py has the same on an in-memory stream."""
    hub, port, f, connect = live
    comment(f)
    token = Tokens().add("codex", "Codex")
    tab = connect()
    tab.request("GET", "/_/live?doc=work/plan.md", headers=cookie(hub))
    stream = tab.getresponse()
    assert read_events(stream, 1)[0][0] == "hello"
    live_doc = hub.entry("work/plan.md").live
    assert live_doc.await_reply("c1") is True and live_doc.waiting() == ["c1"]

    body = json.dumps(rpc("tools/call", {"name": "reply", "arguments": {
        "doc": "work/plan.md", "id": "c1", "text": "Did it.", "role": "action"}}))
    c = connect()
    c.request("POST", "/_/mcp", body, {"Authorization": f"Bearer {token}",
                                       "Content-Type": "application/json"})
    answer = json.loads(c.getresponse().read())
    assert answer["result"]["isError"] is False, answer

    ((name, data),) = read_events(stream, 1, timeout=3)
    assert name == "changed" and data["telling"] == []
    thread = next(x for x in data["comments"] if x["id"] == "c1")
    assert [(r["display"], r["role"]) for r in thread["replies"]] == [("Codex", "action")]
    assert live_doc.waiting() == [] and hub.jobs()["telling"] == []


# ── binding ──────────────────────────────────────────────────────────────────

def test_a_port_that_is_taken_is_not_bound_and_never_moved(tmp_path):
    held = socket.socket()
    held.bind(("127.0.0.1", 0))
    held.listen()
    port = held.getsockname()[1]
    try:
        with pytest.raises(server.PortTaken):
            server.bind(port)
    finally:
        held.close()


def test_the_hub_binds_loopback_only(tmp_path):
    s = server.bind(0)
    try:
        assert s.getsockname()[0] == "127.0.0.1"
    finally:
        s.close()


# ── the name the door signs with, over the wire (SPEC 12) ────────────────────

def _door_reply(live, name_bytes):
    """One `reply` to c1 of plan.md at the door, with the key and `X-Sheaf-As: <name_bytes>` written
    on the socket as they are: http.client would refuse a byte above U+007F, a client need not."""
    hub, port, f, connect = live
    comment(f)
    body = json.dumps(rpc("tools/call", {"name": "reply", "arguments": {
        "doc": "work/plan.md", "id": "c1", "text": "Done."}})).encode()
    head = (b"POST /_/mcp HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Sheaf-Key: %s\r\nX-Sheaf-As: %s\r\n"
            b"Content-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
            % (port, hub.auth.key.encode(), name_bytes, len(body)))
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(head + body)
        got = b""
        while chunk := s.recv(65536):
            got += chunk
    return int(got.split(b" ", 2)[1]), f, got


def test_a_raw_utf8_name_at_the_door_is_refused_and_nothing_is_signed(live):
    status, f, got = _door_reply(live, "Zoë".encode("utf-8"))
    assert status == 400 and b"X-Sheaf-As is not percent-encoded UTF-8" in got
    assert "Done." not in f.read_text(encoding="utf-8")


def test_the_stdio_doors_percent_encoded_name_is_signed_whole_over_the_wire(live):
    import sheafmd.comments as rdc
    status, f, _ = _door_reply(live, b"Zo%C3%AB")
    assert status == 200
    assert rdc.parse(f.read_text(encoding="utf-8")).by_id("c1").replies[-1].by == "Zoë"


@pytest.fixture
def stopping_hub(work):
    """A hub whose stop has begun and is held there: (port, a connection that already served a request)."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    started, release = threading.Event(), threading.Event()
    announce = hub.announce_stop

    def slow_announce(reason):
        announce(reason)
        started.set()
        release.wait(5)
    hub.announce_stop = slow_announce
    kept = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    kept.request("GET", "/_/health")
    r = kept.getresponse()
    assert r.status == 200
    r.read()
    stopper = threading.Thread(target=srv.stop, daemon=True)
    stopper.start()
    assert started.wait(5)
    yield port, kept
    release.set()
    kept.close()
    stopper.join(5)
    srv.close()


def test_a_kept_connection_is_not_served_once_the_hub_is_stopping(stopping_hub):
    """A hub that has begun to stop answers a connection it kept alive with 503 and closes it,
    so the request that follows is not applied by a hub about to exit."""
    port, kept = stopping_hub
    kept.request("GET", "/_/health")
    r = kept.getresponse()
    assert r.status == 503 and r.getheader("Connection") == "close"
    assert json.loads(r.read())["error"]


def test_a_refused_kept_connection_still_gets_its_503_when_it_sent_a_big_body(stopping_hub):
    port, kept = stopping_hub
    kept.request("POST", "/_/save", b"x" * 300_000, {"Content-Type": "application/json"})
    assert kept.getresponse().status == 503


def test_a_new_connection_and_a_stop_are_still_answered_while_the_hub_stops(stopping_hub):
    """Only a kept connection is refused: a new one is served until the listener closes (a proof
    asks `/_/health` on one), and `POST /_/stop` is answered so that its reason keeps its precedence."""
    port, kept = stopping_hub
    fresh = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    fresh.request("GET", "/_/health")
    assert fresh.getresponse().status == 200
    fresh.close()
    kept.request("POST", "/_/stop", "{}", {"Content-Type": "application/json"})
    assert kept.getresponse().status != 503


def test_a_stop_accepted_by_the_hub_refuses_a_kept_connection_at_once(work):
    """`closing` is set when the hub accepts the stop, before the worker thread that does the stop runs."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    hub.announce_stop = lambda reason: time.sleep(5)
    try:
        hub.on_stop("stop")
        assert srv.closing.is_set()
    finally:
        srv.close()
