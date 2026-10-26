"""A hub on a remote box, reached through `ssh -L` with its own port (SPEC 9.2, D21, 9.6).

`ssh -L B:127.0.0.1:A` is a TCP forwarder: what arrives on the local port B is carried to the
port A of the box. `Forwarder` stands in for it, so the browser's side speaks to port B while the
hub, which knows only its own port A, never hears of B. Everything is local; no ssh runs."""
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
import time

import pytest

from helpers import PLAN, stop_listener
from sheafmd import paths
from sheafmd.hub import server
from sheafmd.hub.core import Hub

DOC = "work/plan.md"


class Forwarder:
    """Listens on a free local port and pipes each connection to 127.0.0.1:`target`."""

    def __init__(self, target):
        self.target = target
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self._open: list[socket.socket] = []
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while True:
            try:
                near, _ = self.sock.accept()
            except OSError:
                return
            try:
                far = socket.create_connection(("127.0.0.1", self.target), timeout=10)
            except OSError:
                near.close()
                continue
            self._open += [near, far]
            for a, b in ((near, far), (far, near)):
                threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()

    @staticmethod
    def _pipe(a, b):
        try:
            while data := a.recv(65536):
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        try:
            stop_listener(self.sock, self.thread)
        finally:                                # a stop that raises still closes the open connections
            for s in self._open:
                s.close()


@pytest.fixture
def remote(work, port):
    """The hub on its own port A (`port`), and the forward to it on port B."""
    sock = server.bind(port)
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    fwd = Forwarder(port)
    yield hub, port, fwd.port
    fwd.close()
    srv.close()


def call(port, method, path, headers=None, body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request(method, path, body, headers or {})
        r = c.getresponse()
        return r, r.read()
    finally:
        c.close()


def sign_in(hub, a, b):
    """The browser's first visit, through the forward: the hub's cookie, named after port A."""
    r, _ = call(b, "GET", f"/_/open?key={hub.auth.key}&next=/work/plan.md")
    assert r.status == 303
    return r.getheader("Set-Cookie").split(";")[0]


def test_the_sign_in_through_the_forward_sets_a_cookie_named_after_the_hubs_own_port(remote):
    hub, a, b = remote
    assert a != b
    r, _ = call(b, "GET", f"/_/open?key={hub.auth.key}&next=/work/plan.md")
    assert r.status == 303 and r.getheader("Location") == "/work/plan.md"
    assert r.getheader("Set-Cookie").startswith(f"sheaf_{a}=") and f"sheaf_{b}" not in r.getheader("Set-Cookie")


def test_the_cookie_gets_the_page_through_the_forward(remote):
    hub, a, b = remote
    jar = sign_in(hub, a, b)
    r, body = call(b, "GET", "/work/plan.md", {"Cookie": jar})
    assert r.status == 200 and b"about apples" in body and hub.auth.key.encode() not in body
    r, _ = call(b, "GET", "/work/plan.md")                       # no cookie: the sign-in page
    assert r.status == 401


def test_a_save_through_the_forward_needs_the_origin_of_the_port_it_came_in_on(remote, work):
    from sheafmd.blocks import split_md_blocks
    from sheafmd.source import md_hash
    hub, a, b = remote
    jar = sign_in(hub, a, b)
    text = (work / "plan.md").read_text(encoding="utf-8")
    i = next(i for i, blk in enumerate(split_md_blocks(text)) if blk.content.startswith("Second"))
    body = json.dumps({"doc": DOC, "hash": md_hash(text),
                       "edits": [{"i": i, "html": "<p>Second, from the other machine.</p>"}]})
    head = {"Cookie": jar, "Content-Type": "application/json"}
    r, _ = call(b, "POST", "/_/save", {**head, "Origin": f"http://127.0.0.1:{a}"}, body)
    assert r.status == 403                                       # the page was served at B, not A
    r, out = call(b, "POST", "/_/save", {**head, "Origin": f"http://127.0.0.1:{b}"}, body)
    assert r.status == 200 and json.loads(out)["changed"]
    assert "Second, from the other machine." in (work / "plan.md").read_text(encoding="utf-8")


def test_a_host_that_is_not_loopback_is_refused_through_the_forward_too(remote):
    hub, a, b = remote
    jar = sign_in(hub, a, b)
    r, _ = call(b, "GET", "/work/plan.md", {"Cookie": jar, "Host": f"evil.example:{b}"})
    assert r.status == 403
    r, _ = call(b, "GET", "/work/plan.md", {"Cookie": jar, "Host": f"localhost:{b}"})
    assert r.status == 200


def test_the_event_stream_runs_through_the_forward(remote):
    hub, a, b = remote
    jar = sign_in(hub, a, b)
    s = socket.create_connection(("127.0.0.1", b), timeout=5)
    s.sendall(f"GET /_/live?doc={DOC} HTTP/1.1\r\nHost: 127.0.0.1:{b}\r\nCookie: {jar}\r\n\r\n".encode())
    s.settimeout(5)
    got = b""
    while b"event: hello" not in got:
        got += s.recv(4096)
    s.close()
    assert b"200 OK" in got and b"text/event-stream" in got


# ── two accounts on one machine: each its own port, key and cookie ───────────

def where(home):
    """Where this platform keeps the config file and the state folder of the user whose home is
    `home` (SPEC 4.1): the product answers, so the test names no platform's layout."""
    with pytest.MonkeyPatch.context() as m:
        m.delenv("SHEAF_HOME", raising=False)
        m.setenv("HOME", str(home))
        return paths.config_file(), paths.state_dir()


def account(tmp_path, name, port):
    """What one user of a shared box has: their own home, so their own config.toml, state folder
    and runtime folder. No SHEAF_HOME and no SHEAF_PORT: the port comes from `port =` in the file."""
    home = tmp_path / name
    config, _ = where(home)
    config.parent.mkdir(parents=True)
    config.write_text(f"port = {port}\n")
    (home / "run").mkdir(mode=0o700)
    (home / "tmp").mkdir()
    env = {k: v for k, v in os.environ.items()
           if k not in ("SHEAF_PORT", "SHEAF_HOME") and not k.startswith("XDG_")}
    env.update(HOME=str(home), XDG_RUNTIME_DIR=str(home / "run"), TMPDIR=str(home / "tmp"))
    return env


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def hub_said(proc):
    """What a hub that did not come up has to say: whether it was still running, and its stderr."""
    ran = proc.poll() is None
    if ran:
        proc.terminate()
    try:
        _, err = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()
    return f"{'still running' if ran else f'exited {proc.returncode}'}, stderr: {err.strip()!r}"


def hub_trace(state):
    """What a hub's state folder holds when it did not come up: its files, and the tail of its
    diagnostics log, so a failure on a loaded runner names its cause."""
    try:
        files = sorted(p.name for p in state.iterdir()) if state.is_dir() else "no state folder"
        log = state / "diagnostics.jsonl"
        tail = log.read_text(errors="replace").splitlines()[-10:] if log.exists() else []
    except OSError as e:                  # the trace must never replace the failure it explains
        return f"state folder unreadable: {e!r}"
    return f"state files: {files}, diagnostics tail: {tail}"


def test_a_hub_that_does_not_come_up_is_reported_with_what_it_said(tmp_path):
    env = account(tmp_path, "cy", free_port())
    env["SHEAF_PORT"] = "notanumber"                  # the hub refuses to start and says why
    proc = subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", "cli"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    proc.wait(timeout=30)
    said = hub_said(proc)
    assert "exited 1" in said and "'notanumber' is not a port number" in said


def test_a_hub_that_did_not_come_up_is_reported_with_its_state_folder_and_diagnostics_tail(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "hub.key").write_text("k")
    (state / "diagnostics.jsonl").write_text("".join(f'{{"n": {i}}}\n' for i in range(30)))
    said = hub_trace(state)
    assert "['diagnostics.jsonl', 'hub.key']" in said and '{"n": 29}' in said and '{"n": 19}' not in said
    assert "no state folder" in hub_trace(tmp_path / "absent")


def test_a_hub_that_is_still_running_is_stopped_and_reported_as_such():
    proc = subprocess.Popen([sys.executable, "-c", "import sys, time; print('slow', file=sys.stderr, flush=True); time.sleep(60)"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stderr.readline() == "slow\n"          # it is up and has spoken
    assert hub_said(proc) == "still running, stderr: ''"
    assert proc.poll() is not None


def test_two_accounts_run_two_hubs_at_once_each_with_its_own_port_key_and_cookie(tmp_path):
    pa, pb = free_port(), free_port()
    ea, eb = account(tmp_path, "ada", pa), account(tmp_path, "bob", pb)
    def run(env):
        return subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", "cli"],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    procs = [run(ea), run(eb)]
    try:
        for who, port, proc in (("ada", pa, procs[0]), ("bob", pb, procs[1])):
            pid_file = where(tmp_path / who)[1] / "hub.pid"
            for _ in range(400):
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
                    if pid_file.exists():          # written after the hub holds the port, not with it
                        break
                except OSError:
                    pass
                time.sleep(0.05)
            else:
                pytest.fail(f"no hub on {port}: {hub_said(proc)}; {hub_trace(where(tmp_path / who)[1])}")
        keys = {}
        for who, env, port in (("ada", ea, pa), ("bob", eb, pb)):
            state = where(tmp_path / who)[1]
            keys[who] = (state / "hub.key").read_text().strip()
            assert json.loads((state / "hub.pid").read_text())["port"] == port
            r, _ = call(port, "GET", f"/_/open?key={keys[who]}&next=/")
            assert r.status == 303 and r.getheader("Set-Cookie").startswith(f"sheaf_{port}=")
        assert keys["ada"] != keys["bob"] and pa != pb
        r, _ = call(pb, "GET", f"/_/open?key={keys['ada']}&next=/")      # her key opens nothing of his
        assert r.status == 401
        for p in procs:
            assert p.poll() is None                                         # neither lost the port race
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=30)
