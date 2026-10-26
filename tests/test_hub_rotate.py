"""`sheaf rotate` and `sheaf signin-url` (SPEC 9.3, D13): a new hub key, written whole or not at all;
the old key and every cookie made from it stop working at once; open tabs are told and end their
stream; the MCP tokens are not touched; and the key is printed by `signin-url` and by nothing else."""
import http.client
import json
import os
import socket
import subprocess
import sys
import time

import pytest

from helpers import PLAN, door, rpc, stranger
from sheafmd import diagnostics, paths
from sheafmd.hub import auth as hubauth
from sheafmd.hub import client as hubclient
from sheafmd.hub import server
from sheafmd.hub.core import Hub
from sheafmd.hub.state import Tokens

DOC = "work/plan.md"
URL = "/work/plan.md"


def cookie_header(key, port):
    a = hubauth.Auth(key, port)
    return {"Cookie": f"{a.cookie_name}={a.cookie_value()}"}


# ── the key file ─────────────────────────────────────────────────────────────

def test_rotate_key_writes_a_new_valid_key_with_the_mode_of_the_old_one(sheaf_env):
    old = paths.ensure_key()
    new = paths.rotate_key()
    assert new != old and paths.key_bytes(new) and paths.key_file().read_text() == new + "\n"
    assert paths.key_file().stat().st_mode & 0o777 == 0o600
    assert sorted(p.name for p in paths.key_file().parent.iterdir() if "key" in p.name) == ["hub.key"]
    assert paths.ensure_key() == new


def test_rotate_key_makes_a_key_when_there_is_none(sheaf_env):
    new = paths.rotate_key()
    assert paths.ensure_key() == new


def test_a_rotation_that_fails_midway_leaves_the_old_key_whole_and_no_temp_file(sheaf_env, monkeypatch):
    old = paths.ensure_key()

    def boom(src, dst):
        raise OSError("disk went away")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        paths.rotate_key()
    assert paths.key_file().read_text() == old + "\n"
    assert [p.name for p in paths.key_file().parent.iterdir() if "key" in p.name] == ["hub.key"]


def test_a_file_that_is_not_a_key_is_not_replaced_by_a_rotation(sheaf_env):
    paths.key_file().parent.mkdir(parents=True, exist_ok=True)
    paths.key_file().write_text("my notes, not a key\n")
    with pytest.raises(paths.PathError, match="does not hold a hub key"):
        paths.rotate_key()
    assert paths.key_file().read_text() == "my notes, not a key\n"


# ── the handler ──────────────────────────────────────────────────────────────

def test_rotate_replaces_the_key_and_the_old_key_and_cookie_stop_working_at_once(browser, plan):
    hub = browser.hub
    old_key = hub.auth.key
    old_cookie = {"Cookie": f"{hub.auth.cookie_name}={hub.auth.cookie_value()}"}
    r = browser.post("/_/rotate", cookie=False, key=True)
    assert r.status == 200 and r.json() == {"ok": True}
    new_key = paths.key_file().read_text().strip()
    assert new_key != old_key and hub.auth.key == new_key
    assert old_key not in r.text and new_key not in r.text
    for name, head in (("old key", {"X-Sheaf-Key": old_key}), ("old cookie", old_cookie)):
        page = browser.get(URL, cookie=False, headers=head)
        assert page.status == 401 and "not signed in" in page.text.lower(), name
        assert "text/html" in page.headers["Content-Type"]
        doc = browser.get(f"/_/doc?doc={DOC}", cookie=False, headers=head)
        assert doc.status == 401 and "json" in doc.headers["Content-Type"], name
    assert browser.get(URL).status == 200                                  # the new cookie
    assert browser.get("/_/jobs", cookie=False, key=True).status == 200   # the new key


def test_a_rotation_leaves_one_row_in_the_diagnostics_log_and_no_key(browser, plan):
    """A later reader asking why every tab signed out finds the answer, with the pid of the hub
    that rotated and neither key in the log (SPEC 9.3, 15)."""
    old_key = browser.hub.auth.key
    assert browser.post("/_/rotate", cookie=False, key=True).status == 200
    new_key = paths.key_file().read_text().strip()
    rows = [r for r in diagnostics.read() if r["kind"] == "key-rotated"]
    assert len(rows) == 1 and rows[0]["source"] == "hub" and rows[0]["pid"] == os.getpid()
    log = diagnostics.log_path().read_text(encoding="utf-8")
    assert old_key not in log and new_key not in log


def test_a_rotation_that_fails_leaves_no_key_rotated_row(browser, plan, monkeypatch):
    def boom(src, dst):
        raise OSError("disk went away")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        browser.hub.rotate()
    assert [r for r in diagnostics.read() if r["kind"] == "key-rotated"] == []


def test_the_health_proof_is_made_with_the_new_key(browser):
    hub = browser.hub
    old = hub.auth.key
    browser.post("/_/rotate", cookie=False, key=True)
    nonce = "ab" * 16
    got = browser.get(f"/_/health?nonce={nonce}", cookie=False).json()
    assert got["proof"] == hubauth.Auth(hub.auth.key, hub.port).proof(nonce)
    assert got["proof"] != hubauth.Auth(old, hub.port).proof(nonce)


def test_rotating_needs_the_key_and_a_signed_in_browser_cannot(browser):
    r = browser.post("/_/rotate", cookie=True, key=False)
    assert r.status == 403 and paths.key_file().read_text().strip() == browser.hub.auth.key
    assert browser.post("/_/rotate", cookie=False, key=False).status == 401


def test_a_hub_that_starts_after_a_rotation_reads_the_new_key_and_the_new_cookie_still_works(browser, plan):
    hub = browser.hub
    browser.post("/_/rotate", cookie=False, key=True)
    cookie = {"Cookie": f"{hub.auth.cookie_name}={hub.auth.cookie_value()}"}
    again = Hub(port=hub.port, key=paths.ensure_key(), started_by="test")
    assert again.auth.key == hub.auth.key and again.auth.cookie_value() == hub.auth.cookie_value()
    assert cookie["Cookie"].split("=", 1)[1] == again.auth.cookie_value()


def test_every_open_stream_gets_signed_out_and_the_hub_ends_it(browser, plan):
    hub = browser.hub
    live = browser.get(f"/_/live?doc={DOC}")
    sub = live.stream
    assert sub.drain()[0][0] == "hello"
    browser.post("/_/rotate", cookie=False, key=True)
    assert [name for name, _ in sub.drain()] == ["signed-out"]


def test_an_open_index_stream_gets_signed_out_and_the_hub_ends_it(browser, plan):
    """The index page streams the list of documents and their dots: after a rotation its old
    cookie must not go on receiving them."""
    live = browser.get("/_/live")
    sub = live.stream
    assert sub.drain()[0][0] == "hello"
    browser.post("/_/rotate", cookie=False, key=True)
    assert [name for name, _ in sub.drain()] == ["signed-out"]


def test_rotate_does_not_read_or_write_the_mcp_tokens(browser, plan):
    token = Tokens().add("codex", "Codex")
    assert door(browser, rpc("ping"), token=token).status == 200       # it has been used: last_used is set
    f = paths.state_dir() / "tokens.json"
    os.utime(f, ns=(1_000_000_000, 1_000_000_000))
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    browser.post("/_/rotate", cookie=False, key=True)
    assert (f.read_bytes(), f.stat().st_mtime_ns) == before


def test_an_mcp_token_keeps_working_across_a_rotation_and_the_old_key_does_not(browser, plan):
    """Done-when of 24, "MCP tokens keep working": a token is its own credential (9.7), not
    something made from the hub key."""
    token = Tokens().add("codex", "Codex")
    ask = rpc("tools/call", {"name": "threads", "arguments": {"doc": DOC, "status": "all"}})
    old_key = browser.hub.auth.key
    assert door(browser, ask, token=token).status == 200
    assert door(browser, rpc("ping"), as_name="Claude").status == 200          # the key, before
    assert browser.post("/_/rotate", cookie=False, key=True).status == 200
    for n in (1, 2):                                                        # more than once: it is not a grace period
        res = door(browser, ask, token=token)
        assert res.status == 200 and "error" not in res.json(), res.text
    assert door(browser, rpc("ping"), as_name="Claude").status == 200          # the new key opens the door
    stale = door(browser, rpc("ping"), key=False, headers={"X-Sheaf-Key": old_key, "X-Sheaf-As": "Claude"})
    assert stale.status == 401                                                 # the old key does not
    assert [t.name for t in Tokens().list()] == ["codex"]                   # and the token is still on the list


def test_a_token_that_was_revoked_before_a_rotation_is_not_brought_back_by_it(browser, plan):
    token = Tokens().add("codex", "Codex")
    Tokens().revoke("codex")
    browser.post("/_/rotate", cookie=False, key=True)
    assert door(browser, rpc("ping"), token=token).status == 401


def rotation_lands_after(hub, check):
    """Make the hub's current Auth rotate the key right after it answers yes to `check`
    ("key_ok" or "cookie_ok"): a rotation that lands in another thread between a request's
    credential check and the rest of its handling."""
    real = getattr(hub.auth, check)

    def checked(*args):
        ok = real(*args)
        if ok:
            hub.rotate()
        return ok
    setattr(hub.auth, check, checked)


def test_a_sign_in_that_a_rotation_overtakes_gets_no_cookie_of_the_new_key(browser):
    """The key was good when it was checked; what the answer carries must not open the hub now."""
    hub = browser.hub
    old_key = hub.auth.key
    rotation_lands_after(hub, "key_ok")
    res = browser.get(f"/_/open?key={old_key}&next=/", cookie=False)
    assert res.status in (303, 401)
    assert not hub.auth.cookie_ok(res.headers.get("Set-Cookie", ""))
    assert hub.auth.key != old_key


def test_a_stream_that_a_rotation_overtakes_is_told_it_is_signed_out(browser, plan):
    """The cookie was good when it was checked; a stream opened after the rotation told every
    other stream must hear the same, or it stays on the old cookie for as long as it likes."""
    hub = browser.hub
    rotation_lands_after(hub, "cookie_ok")
    res = browser.get(f"/_/live?doc={DOC}")
    assert res.status == 200
    assert [name for name, _ in res.stream.drain()] == ["hello", "signed-out"]


def test_an_index_stream_that_a_rotation_overtakes_is_told_it_is_signed_out(browser, plan):
    hub = browser.hub
    rotation_lands_after(hub, "cookie_ok")
    res = browser.get("/_/live")
    assert res.status == 200
    assert [name for name, _ in res.stream.drain()] == ["hello", "signed-out"]


# ── over a real socket ───────────────────────────────────────────────────────

@pytest.fixture
def live(work, port):
    sock = server.bind(port)
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    yield hub, port
    srv.close()


def read_until(s, needle, seconds=10):
    s.settimeout(0.5)
    buf, end = b"", time.time() + seconds
    while needle not in buf and time.time() < end:
        try:
            got = s.recv(4096)
        except socket.timeout:
            continue
        if not got:
            break
        buf += got
    return buf


def test_an_open_tab_hears_signed_out_and_its_stream_ends(live):
    hub, port = live
    key = hub.auth.key
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    head = cookie_header(key, port)["Cookie"]
    s.sendall(f"GET /_/live?doc={DOC} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nCookie: {head}\r\n\r\n".encode())
    assert b"event: hello" in read_until(s, b"event: hello")
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("POST", "/_/rotate", "{}", {"X-Sheaf-Key": key, "Content-Type": "application/json"})
    r = c.getresponse()
    assert r.status == 200 and json.loads(r.read()) == {"ok": True}
    got = read_until(s, b"event: signed-out")
    assert b"event: signed-out" in got
    assert s.recv(1) == b""                      # the hub closed it: this tab connects no more
    # the tab that reconnects with the old cookie is refused, not served
    c.request("GET", f"/_/live?doc={DOC}", headers={"Cookie": head})
    assert c.getresponse().status == 401
    s.close()


# ── the commands ─────────────────────────────────────────────────────────────

def keys_in(text):
    return [k for k in (paths.key_file().read_text().strip(),) if k in text]


def test_sheaf_rotate_with_a_hub_running_rotates_it_and_prints_no_key(sheaf, port):
    sheaf("start")
    old = paths.key_file().read_text().strip()
    r = sheaf("rotate")
    new = paths.key_file().read_text().strip()
    assert r.code == 0 and new != old
    assert "key rotated" in r.out and "sheaf open" in r.out and "sheaf signin-url" in r.out
    assert old not in r.out + r.err and new not in r.out + r.err
    assert sheaf("status").code == 0                    # the hub and the command agree on the new key
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", "/_/jobs", headers={"X-Sheaf-Key": old})
    assert c.getresponse().status == 401


def test_a_token_made_by_the_command_works_on_the_hub_before_and_after_sheaf_rotate(sheaf, port):
    sheaf("start")
    made = sheaf("token", "add", "codex")
    token = next(w for w in made.out.split() if w.startswith("sheaf_mcp_"))

    def ping():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", "/_/mcp", json.dumps(rpc("ping")),
                  {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, r.read()

    assert ping()[0] == 200
    old = paths.key_file().read_text().strip()
    assert sheaf("rotate").code == 0 and paths.key_file().read_text().strip() != old
    status, body = ping()
    assert status == 200 and json.loads(body)["result"] == {}
    assert token not in sheaf("token", "list").out                     # the list still shows the name, never the token
    assert sheaf("token", "list").out.split()[0] == "codex"


def test_sheaf_rotate_with_no_hub_replaces_the_key_file_and_says_so(sheaf, port):
    old = paths.ensure_key()
    r = sheaf("rotate")
    new = paths.key_file().read_text().strip()
    assert r.code == 0 and new != old
    assert "no hub is running" in r.out and "key was replaced" in r.out
    assert old not in r.out + r.err and new not in r.out + r.err


def test_a_hub_that_starts_while_the_key_is_being_replaced_comes_up_on_the_new_key(port):
    """`sheaf rotate` on a machine with no hub replaces the key file; a hub that is starting at
    that moment must not take its port on the key it is about to lose."""
    paths.ensure_key()
    with paths.key_lock():                        # a rotation is in the middle of its work
        hubclient.spawn_hub("cli")
        time.sleep(1.0)
        assert hubclient.client().challenge() is None      # the hub waits: it has not bound the port
        paths.rotate_key()
    c = hubclient.client()                        # reads the new key
    got = None
    for _ in range(200):
        got = c.challenge()                       # an Impostor here is a hub on the old key
        if got is not None:
            break
        time.sleep(0.05)
    assert got is not None


def test_sheaf_rotate_with_no_hub_waits_for_a_hub_that_is_taking_its_port(port):
    old = paths.ensure_key()
    with paths.key_lock():                        # a hub is between reading the key and binding
        p = subprocess.Popen([sys.executable, "-m", "sheafmd", "rotate"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                p.wait(timeout=1.0)
            assert paths.key_file().read_text().strip() == old
        except BaseException:
            p.kill()
            p.communicate()
            raise
    out, err = p.communicate(timeout=20)
    assert p.returncode == 0, err
    assert "no hub is running" in out and paths.key_file().read_text().strip() != old


def test_sheaf_rotate_will_not_hand_the_new_key_to_something_that_is_not_the_hub(sheaf, port):
    s = stranger(port)
    try:
        before = paths.ensure_key()
        r = sheaf("rotate")
        assert r.code == 1 and "something else holds" in r.err
        assert paths.key_file().read_text().strip() == before
    finally:
        s.close()


def test_signin_url_prints_the_url_that_signs_a_browser_in_and_nothing_else_on_stdout(sheaf, port):
    r = sheaf("signin-url")
    key = paths.key_file().read_text().strip()
    assert r.code == 0 and r.out.strip() == f"http://127.0.0.1:{port}/_/open?key={key}&next=/"
    assert len(r.out.strip().splitlines()) == 1 and "agent" not in r.err
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", r.out.strip().split(str(port), 1)[1])
    got = c.getresponse()
    assert got.status == 303 and f"sheaf_{port}=" in got.getheader("Set-Cookie")


def test_signin_url_warns_when_an_agent_runs_it_and_still_prints_the_url_alone_on_stdout(sheaf, port, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-1")
    r = sheaf("signin-url")
    key = paths.key_file().read_text().strip()
    assert "  ! this URL holds your hub key; open it yourself, never paste it to an agent" in r.err
    assert key not in r.err and r.out.strip().startswith("http://127.0.0.1:") and key in r.out


def test_the_service_tip_of_a_first_start_does_not_land_in_the_signin_url_output(sheaf, port):
    r = sheaf("signin-url")
    assert "tip:" not in r.out


def test_no_other_command_prints_the_key(sheaf, port, work):
    doc = work / "plan.md"
    doc.write_text(PLAN, encoding="utf-8")
    seen = []
    for argv in (("start",), ("status",), ("version",), ("diag",), ("open", "--no-browser", doc),
                 ("restart",), ("rotate",), ("status",), ("stop",), ("stop",)):
        before = paths.key_file().read_text().strip() if paths.key_file().exists() else ""
        r = sheaf(*argv)
        after = paths.key_file().read_text().strip() if paths.key_file().exists() else ""
        for k in (before, after):
            if k:
                assert k not in r.out + r.err, argv
        seen.append(argv[0])
    assert seen[-1] == "stop"
