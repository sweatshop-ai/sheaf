"""Shared by the tests: pandoc is always the bundled one, never whatever is on PATH; the
brand words no output may hold; small file helpers; `python -m sheafmd` as a real process."""
import fcntl
import http.client
import json
import os
import pwd
import random
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

import pypandoc

import sheafmd.comments as rdc
from sheafmd import config, diagnostics, paths, signals
from sheafmd.source import update_file

NOW = time.time()

# The words the product must not print into a page, a log or the output of a command.
BRAND_WORDS = ("tiroir", "acme")
CREDIT = f"Made by {BRAND_WORDS[0]}. A hosted version is coming."


def hub_rows(*kinds):
    """The rows the hub wrote to the diagnostics log, of these kinds (all of them when none is named)."""
    return [r for r in diagnostics.read() if r["source"] == "hub" and (not kinds or r["kind"] in kinds)]


def _has_proc() -> bool:
    try:
        with open("/proc/self/cmdline", "rb"):
            return True
    except OSError:
        return False


def proc_state(pid: int) -> str:
    """"alive", "zombie" (ended, not yet reaped) or "gone", read without reaping anything. Where
    there is a /proc (Linux) its stat file says; macOS has none, so there `kill -0` finds the
    pid and `ps` prints its state."""
    if _has_proc():
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            return "gone"
        return "zombie" if state == "Z" else "alive"
    if not signals.exists(pid):                  # another user's process exists too
        return "gone"
    ps = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    state = ps.stdout.strip()
    if not state:
        return "gone"
    return "zombie" if state.startswith("Z") else "alive"


def is_stopped(pid: int) -> bool:
    """The process is stopped (SIGSTOP, state `T`): alive, and running nothing. Linux only."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "T"
    except OSError:
        return False


def gone(pid: int) -> bool:
    """The process has ended. A hub that a command of a test started is a child of the test
    process, and stays a zombie until reaped (a shell's `sheaf` leaves it to init)."""
    signals.reap(pid)
    return proc_state(pid) != "alive"


def stop_hub(pid: int):
    """SIGTERM, then SIGKILL after five seconds, to one process of this user's (`sheafmd.signals`: a
    -1, 0 or 1 from `hub.pid` is refused on macOS as on Linux, sheaf#85). Where there is a /proc
    (Linux), only a process that still is a sheaf hub: a pid that ended and was given to something
    else is left alone. macOS has none, so there the command line cannot be checked."""
    try:
        if _has_proc():
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                if b"sheafmd" not in f.read():
                    return
        signals.send(pid, signal.SIGTERM)
    except (OSError, signals.Refused):
        return
    for _ in range(100):
        if gone(pid):
            return
        time.sleep(0.05)
    try:
        signals.send(pid, signal.SIGKILL)
    except (OSError, signals.Refused):
        pass


# A real hub that serves `LATE_BY` seconds after its bind: what a hub that is starting looks like on a
# loaded machine. The port listens from the bind on and nothing answers until the hub serves (`server.run`),
# so a challenge in between waits and gets nothing. `python -c LATE_HUB -m sheafmd hub --started-by WHO` has
# the command line of a hub.
LATE_HUB = r'''
import os, sys, time
from sheafmd.hub import server
serve = server.HubServer.start
def late(self):
    time.sleep(float(os.environ["LATE_BY"]))
    serve(self)
server.HubServer.start = late
from sheafmd.cli import main
raise SystemExit(main(sys.argv[3:]))
'''


def late_hub_command(started_by: str) -> list[str]:
    return [sys.executable, "-c", LATE_HUB, "-m", "sheafmd", "hub", "--started-by", started_by]


def start_late_hub(started_by: str, late_by: float):
    """`hubclient.spawn_hub`, for a hub that serves `late_by` seconds after its bind."""
    subprocess.Popen(late_hub_command(started_by), env={**os.environ, "LATE_BY": str(late_by)},
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


PORT_FLOOR = 10000

# The ports from PORT_FLOOR to 49152 that Chromium will not load a page from
# (`net::ERR_UNSAFE_PORT`): `kRestrictedPorts` in Chromium's net/base/port_util.cc
# and the Fetch standard's "bad port" list. 10080 (Amanda) is the only one in
# the range; the next one below is 6697.
BROWSER_REFUSES = frozenset({10080})


def _dynamic_range_start() -> int:
    """Where the kernel starts handing ports to a `bind(0)`: the first number of
    `ip_local_port_range` on Linux, 49152 on macOS and the BSDs."""
    try:
        return int(Path("/proc/sys/net/ipv4/ip_local_port_range").read_text().split()[0])
    except OSError:
        return 49152


def port_locks_folder() -> Path:
    """Where a claim keeps the lock file of each port: `/tmp`, whatever TMPDIR says, so that every
    suite of this user (each with a TMPDIR of its own) meets the same files."""
    return Path("/tmp") / f"sheaf-test-ports-{os.getuid()}"


def claim_port(candidates=None):
    """`(port, release)`: a port 127.0.0.1 has no listener on, that no other claim holds until
    `release()` is called, and that no `bind(0)` can be handed.

    It is taken from below the kernel's dynamic range, so a process that asks the kernel for any free
    port never gets it (a port the fixture has freed could otherwise be handed to a neighbour's listener
    before the test's hub binds it, and `challenge()` would answer with a stranger). Another suite that
    claims a port the same way is kept off it by a lock on one file per port, in a folder that
    does not depend on TMPDIR; the kernel drops the lock when its process ends. A port the browser
    will not load a page from (`BROWSER_REFUSES`) is never handed out. `candidates` is for the
    tests: the ports to try, in order."""
    if candidates is None:
        top = min(_dynamic_range_start(), 49152)
        if top - PORT_FLOOR < 1000:
            raise RuntimeError(f"no free port: the kernel's dynamic range starts at {top}, "
                               f"leaving no room below it from {PORT_FLOOR}")
        rng = random.SystemRandom()
        candidates = (p for p in (rng.randrange(PORT_FLOOR, top) for _ in range(500))
                      if p != config.DEFAULT_PORT)
    folder = port_locks_folder()
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.stat().st_uid != os.getuid():
        raise RuntimeError(f"no free port: {folder} belongs to someone else")
    for port in candidates:
        if port in BROWSER_REFUSES:
            continue
        fd = os.open(folder / str(port), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        except OSError:                         # held by another claim, or something listens
            os.close(fd)
            continue
        return port, lambda: os.close(fd)
    raise RuntimeError("no free port among the candidates")


def wait_until_refused(port: int, seconds: float, connect=socket.create_connection) -> bool:
    """True once a connection to 127.0.0.1:port is refused (nothing listens any more), False when
    `seconds` pass first. Only a refusal ends it: a connect that lands while a listener closes can
    be reset, and one that meets a full backlog times out, and in both the port is going away,
    not gone."""
    deadline = time.time() + seconds
    while True:                                 # asks at least once, however long the process stalled
        try:
            connect(("127.0.0.1", port), timeout=0.2).close()
        except ConnectionRefusedError:
            return True
        except (ConnectionResetError, TimeoutError):
            pass
        if time.time() >= deadline:
            return False
        time.sleep(0.05)


def stop_listener(sock: socket.socket, thread: threading.Thread | None, timeout: float = 5):
    """Let go of a listening socket whose accept loop runs on `thread`. `close()` alone does not:
    a thread blocked in `accept()` holds the kernel socket, so the port stays in LISTEN, a connect
    to it is still taken, and the thread never ends. `shutdown` wakes the accept (Linux, where CI
    runs). Then wait for the thread, and close only once it is gone: the kernel resolves
    `accept(fd)` when the syscall is entered, so a thread that read its fd before the close and is
    slow to enter would accept on whichever socket holds that number by then, a later test's.
    When the thread outlives `timeout` the descriptor stays open and this raises, so the leak is
    loud and the number is never handed out again. Where shutdown of a listening socket is refused
    (macOS) the socket is only closed, as before."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
        woken = True
    except OSError:
        woken = False
    if woken and thread is not None and thread is not threading.current_thread():
        thread.join(timeout)
        assert not thread.is_alive(), (
            f"the accept thread {thread.name} is still running {timeout} s after the shutdown of "
            f"fd {sock.fileno()}: left open, so its number cannot reach a later listener")
    socket.socket.close(sock)                  # not `sock.close()`: a `Listener` calls this from its own


class Listener(socket.socket):
    """The socket of `stranger`: `close()` ends the listener, not only the descriptor."""
    thread = None                              # set by whoever starts the accept loop

    def close(self):
        stop_listener(self, self.thread)


def stranger(port: int) -> socket.socket:
    """Something that is not a hub holding `port`: it answers every request with a 200 and `{}`,
    which is no proof of the key (SPEC 9.4). Close the socket to let go of the port. One that only
    listens and never answers is not this: nothing answered, which `challenge()` says differently."""
    s = Listener()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(5)

    def serve():
        while True:
            try:
                c, _ = s.accept()
            except OSError:
                return
            with c:
                try:
                    c.recv(65536)
                    c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
                except OSError:
                    pass
    s.thread = threading.Thread(target=serve, daemon=True)
    s.thread.start()
    return s


def pandoc(args, text):
    """Run the bundled pandoc on text and return its stdout."""
    r = subprocess.run([pypandoc.get_pandoc_path(), *args], input=text,
                       capture_output=True, text=True, check=True)
    return r.stdout


def active_content(page: str) -> list[str]:
    """What a browser could run or load from the HTML, read by the standard library's
    parser (not the sanitiser's): script elements, on* attributes, javascript: and
    other scripting addresses. An empty list means none."""
    from html.parser import HTMLParser
    found = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            # the page's own head has <meta charset> and <meta name=viewport>; a meta that
            # redirects or sets a policy is http-equiv.
            if tag in ("script", "iframe", "object", "embed", "applet", "base", "link",
                       "form", "frame", "frameset", "template", "noscript") or (
                    tag == "meta" and any(k == "http-equiv" for k, _ in attrs)):
                found.append(f"<{tag}>")
            for k, v in attrs:
                if k.startswith("on") or k in ("srcdoc", "formaction", "srcset", "ping"):
                    found.append(f"{k}={v}")
                if k in ("href", "src", "action", "poster", "background", "xlink:href") and v:
                    s = "".join(v.split()).lower()
                    if s.startswith(("javascript:", "vbscript:", "data:text", "data:image/svg")):
                        found.append(f"{k}={v}")
        handle_startendtag = handle_starttag
    P(convert_charrefs=True).feed(page)
    return found


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def md(path, text="# T\n"):
    """A small markdown document at `path`."""
    return write(path, text)


def make_repo(path):
    """An empty git repository at `path` (made, with its parents), as a resolved path."""
    path = Path(path)
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, capture_output=True)
    return path.resolve()


def wait_until_executable(path, seconds: float = 5.0):
    """Return once no process holds `path` open for writing, so the product's own exec of it
    cannot fail with ETXTBSY ("Text file busy"). A thread of the test forking while this one
    writes the file gives its child a copy of the write handle until that child's exec, and
    the exec of the file waits on nothing: it fails. A read lease is refused (EAGAIN) while
    any process has the file open for writing, which is the condition itself. Where the
    kernel has no leases the exposure is Linux's and there is nothing to wait for."""
    if not hasattr(fcntl, "F_SETLEASE"):
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        end = time.monotonic() + seconds
        while True:
            try:
                fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_RDLCK)
            except BlockingIOError:
                if time.monotonic() > end:
                    raise TimeoutError(f"{path} is still open for writing in another process")
                time.sleep(0.001)
            except OSError:                         # leases off, or not ours to take: no signal
                return
            else:
                fcntl.fcntl(fd, fcntl.F_SETLEASE, fcntl.F_UNLCK)
                return
    finally:
        os.close(fd)


def write_executable(path, text):
    """A script the product will exec: written, closed, and only then handed back, once no
    forked sibling still holds a write handle on it (see `wait_until_executable`)."""
    path = Path(path)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    wait_until_executable(path)
    return path


GIT_FAILS = ["refuses", "missing"]


def git_fails(how, monkeypatch, tmp_path):
    """From here on git names neither a work tree nor a git directory (SPEC 8.2): it refuses every
    repository as one owned by another account (`refuses`: `detected dubious ownership`, as on a server
    where a member's folder is not the hub's account's), or it is not there (`missing`)."""
    if how == "refuses":
        monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
        monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")      # a system `safe.directory = *` would let git in
    else:
        (tmp_path / "no-git").mkdir()
        monkeypatch.setenv("PATH", str(tmp_path / "no-git"))


def git_dirs_in(work: Path, text: str) -> Path:
    """In the root `work`, which is no git repo, a git repo `sub` holding a bare repo `keep.git`, with `text` in a
    page in each git directory (`sub/.git/x.md`, `sub/keep.git/x.md`) and in `sub`'s work tree (`sub/b.md`)."""
    subprocess.run(["git", "init", "-q", str(work / "sub")], check=True, capture_output=True)
    subprocess.run(["git", "init", "-q", "--bare", str(work / "sub" / "keep.git")], check=True, capture_output=True)
    for rel in ("sub/.git/x.md", "sub/keep.git/x.md", "sub/b.md"):
        (work / rel).write_text(text, encoding="utf-8")
    return work


def names_in(folder):
    return sorted(p.name for p in Path(folder).iterdir())


def brand_words_in(text, tmp_path):
    """The brand words in `text`, with this test's own temp folder blanked first: the
    operating system puts the user's name into /tmp/pytest-of-<user>."""
    for p in {str(tmp_path), str(tmp_path.resolve())}:
        text = text.replace(p, "<tmp>")
    return [w for w in BRAND_WORDS if w in text.lower()]


def run_module(*argv, cwd, env=None):
    """`python -m sheafmd ...` as a real process, with this test's environment (plus `env`)."""
    return subprocess.run([sys.executable, "-m", "sheafmd", *map(str, argv)], cwd=cwd,
                          capture_output=True, text=True, timeout=120,
                          env={**os.environ, **(env or {})})


PLAN = """# Plan

First paragraph, about apples.

Second paragraph, about pears.

- one
- two

```python
print("code")
```

Last paragraph.
"""


def page_meta(html: str) -> dict:
    """The page's meta block, as the script reads it."""
    found = re.findall(r'<script id="rd-edit-meta" type="application/json">(.*?)</script>',
                        html, re.S)
    assert len(found) == 1
    return json.loads(found[-1])


def thread(cid, by, *replies, status="open", body="Why?"):
    """A comment as the markdown holds it; `replies` are the authors of its replies."""
    c = rdc.Comment(id=cid, by=by, at="2026-10-13T10:00", status=status, quote="First paragraph",
                    body=body, replies=[rdc.Reply(r, "2026-10-13T10:05", "ok") for r in replies])
    return rdc.format(c, one_line=False)


def with_threads(*raw):
    """PLAN with the given comments written after its first words."""
    return PLAN.replace("First paragraph", "First paragraph" + "".join(raw), 1)


def read_events(resp, n, timeout=8.0):
    """The first n events of a text/event-stream response: [(name, data)]."""
    out, name, data = [], None, None
    deadline = time.time() + timeout
    while len(out) < n and time.time() < deadline:
        line = resp.fp.readline().decode("utf-8")
        if not line:
            break
        line = line.rstrip("\n")
        if line.startswith("event: "):
            name = line[7:]
        elif line.startswith("data: "):
            data = json.loads(line[6:])
        elif line == "" and name:
            out.append((name, data))
            name = data = None
    return out


# ── the hub, in memory ───────────────────────────────────────────────────────

class Browser:
    """Stands in for the browser and the CLI at the edge of the handler: no socket, no thread.
    `get`/`post` send what each of them sends. `cookie=True` (the default) signs the request in
    as a browser that went through /_/open; `key=True` as a CLI that holds the hub key."""

    def __init__(self, hub, handler):
        self.hub, self.handler = hub, handler

    def request(self, method, path, *, body=None, cookie=True, key=False, host=None,
                origin=True, headers=None, raw=None):
        host = host or f"127.0.0.1:{self.hub.port}"
        h = {"Host": host}
        if cookie:
            h["Cookie"] = f"{self.hub.auth.cookie_name}={self.hub.auth.cookie_value()}"
        if key:
            h["X-Sheaf-Key"] = self.hub.auth.key
        if origin and method == "POST":
            h["Origin"] = origin if isinstance(origin, str) else f"http://{host}"
        h.update(headers or {})
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        if data:
            h["Content-Type"] = "application/json"
            h["Content-Length"] = str(len(data))
        return self.handler.handle(method, path, h, data)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body if body is not None else {}, **kw)


def browser_on(hub):
    """A `Browser` on `hub` with the handler's socket check off: no connection to look up, so the check of
    who follows a sign-in link allows (test_hub_peer.py runs the real one)."""
    from sheafmd.hub.handler import Handler
    return Browser(hub, Handler(hub, peer_check=lambda conn: None))


# The four operations that find a comment by its id, with the fields each sends.
BY_ID = [("reply", {"id": "c1", "body": "Done"}), ("status", {"id": "c1", "status": "resolved"}),
         ("edit", {"id": "c1", "body": "Fix it now."}), ("delete", {"id": "c1"})]


# ── the MCP door, through the handler in memory ──────────────────────────────

def rpc(method, params=None, id=1):
    """One JSON-RPC message; `id=None` makes it a notification."""
    msg = {"jsonrpc": "2.0", "method": method}
    if id is not None:
        msg["id"] = id
    if params is not None:
        msg["params"] = params
    return msg


DEFAULT_NAME = object()      # `door(as_name=DEFAULT_NAME)`: the usual name; `None` sends none


def door(browser, message=None, *, token=None, key=True, as_name=DEFAULT_NAME, raw=None, **kw):
    """One POST to the door, signed in as the stdio door is (the key and a name, `Claude` unless
    `as_name` says another; `as_name=None` sends none), or with a token. No cookie unless a test
    asks for one."""
    h = dict(kw.pop("headers", {}))
    if token:
        h["Authorization"] = f"Bearer {token}"
        key = False
    if as_name is DEFAULT_NAME:
        as_name = "Claude" if key else None
    if as_name is not None:
        h["X-Sheaf-As"] = as_name
    kw.setdefault("cookie", False)
    return browser.request("POST", "/_/mcp", body=message, key=key, headers=h, raw=raw, **kw)


def call(browser, tool, as_name="Claude", token=None, **args):
    """(is_error, what the tool said): the parsed JSON of a result, or the sentence of an error."""
    res = door(browser, rpc("tools/call", {"name": tool, "arguments": args}),
               token=token, as_name=None if token else as_name)
    assert res.status == 200, res.text
    got = res.json()
    assert "error" not in got, got
    out = got["result"]
    assert [c["type"] for c in out["content"]] == ["text"]
    text = out["content"][0]["text"]
    return out["isError"], (text if out["isError"] else json.loads(text))


def ok(browser, tool, **kw):
    is_error, got = call(browser, tool, **kw)
    assert not is_error, got
    return got


def refused(browser, tool, **kw):
    is_error, got = call(browser, tool, **kw)
    assert is_error and isinstance(got, str) and got, got
    assert got.endswith(".") and "\n" not in got
    return got


def refused_as_not_there(browser, tool, doc, gone, **kw):
    """The door refuses `doc` with the very answer it gives `gone`, a document that is not there."""
    said = refused(browser, tool, doc=doc, **kw)
    assert said == refused(browser, tool, doc=gone, **kw).replace(gone, doc), doc


def comment(path, quote="Second paragraph", body="Why pears?", by="Ada"):
    """A comment c1 on the file, written the way the page writes one."""
    def add(t):
        blk, s, e = rdc.find_quote(t, quote)
        return rdc.add_comment(t, blk, s, e, quote, body, by, "2026-10-14T10:00")[0]
    update_file(path, add)


def writes_from_outside(path, live, n):
    """`n` writes to the file from outside (an agent, the CLI), each caught up by its Live Document `live`
    as the watcher does for an open tab: `n` more versions the hub hands out (SPEC 7.4)."""
    for i in range(n):
        update_file(path, lambda t, i=i: t + f"\nFrom outside {i}.\n")
        live.refresh()


def hold_job(hub, address, cid="c1", kind="ask"):
    """A job of the hub's runner that runs until the returned event is set: an Ask or a Tell
    without a child process. `(job, release)`."""
    release = threading.Event()
    job = hub.runner.start(kind, address, cid, lambda j: release.wait(10))
    return job, release


# ── proxy mode (SPEC 9.9) ────────────────────────────────────────────────────

class UnixHTTP(http.client.HTTPConnection):
    """An HTTP connection to a Unix socket: what the proxy opens to the hub's proxy socket."""

    def __init__(self, path, timeout=10):
        super().__init__("localhost", timeout=timeout)
        self.unix_path = str(path)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.unix_path)


def proxy_table(sock, members, origin="https://chat.example.com", user=None) -> str:
    """A `[proxy]` table of config.toml: `members` is {id: (name, [folders])}; `user` is the
    proxy's account, the test's own by default."""
    user = user or pwd.getpwuid(os.getuid()).pw_name
    out = [f'[proxy]\norigin = "{origin}"\nsocket = "{sock}"\nproxy_user = "{user}"\n']
    for mid, (name, folders) in members.items():
        roots = ", ".join(json.dumps(str(f)) for f in folders)
        out.append(f'\n[proxy.members."{mid}"]\nname = {json.dumps(name)}\nroots = [{roots}]\n')
    return "".join(out)


BEA = "0f8fad5b-d9cb-469f-a165-70867728950e"        # the front's ids of two members
CAL = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
FRONT = "https://chat.example.com"


class Front:
    """Stands in for the proxy at the edge of the handler, after the verifier's 2xx: a request on
    the proxy socket, in memory, from the proxy's account (`uid`), with `X-Sheaf-Member` set to
    `member`, the front's Host and, on a POST, the front's Origin."""

    def __init__(self, hub, handler):
        self.hub, self.handler = hub, handler

    def request(self, method, path, *, member=BEA, body=None, host=None, origin=True, uid=None,
                headers=None, raw=None, conn=True):
        from sheafmd.hub import proxy
        cfg = self.hub.proxy
        h = {"Host": host if host is not None else cfg.host}
        if member:
            h["X-Sheaf-Member"] = member
        if origin and method == "POST":
            h["Origin"] = origin if isinstance(origin, str) else cfg.origin
        h.update(headers or {})
        data = raw if raw is not None else (b"" if body is None else json.dumps(body).encode())
        if data:
            h["Content-Type"] = "application/json"
            h["Content-Length"] = str(len(data))
        peer = proxy.Peer(cfg.uid if uid is None else uid) if conn else None
        return self.handler.handle(method, path, h, data, conn=peer, via="proxy")

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.request("POST", path, body=body if body is not None else {}, **kw)


class Opener:
    """Stands in for `webbrowser.open`: writes down the addresses `sheaf open` asks it to open."""

    def __init__(self):
        self.opened = []
        self.result = True

    def __call__(self, url, *a, **k):
        self.opened.append(url)
        return self.result


def http_get(port, path, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.request("GET", path, headers=headers or {})
    r = c.getresponse()
    return r, r.read()


def hub_alive(port) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        return True
    except OSError:
        return False


def key() -> str:
    return paths.key_file().read_text().strip()


class Impostor:
    """Something that is not a hub and holds the port. It answers every request the way a hub
    would if it were willing to be trusted, and writes down everything it is sent."""

    def __init__(self, port, answer):
        self.seen = []
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(8)
        self.answer = answer
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            c.settimeout(2)
            try:
                data = c.recv(65536)
                self.seen.append(data)
                if self.answer is not None:
                    c.sendall(self.answer)
            except OSError:
                pass
            finally:
                c.close()

    def close(self):
        stop_listener(self.sock, self.thread)


class Silent(Impostor):
    """Something on the port that takes the request and answers nothing: it holds the connection
    open (`how="hold"`), closes it (`"close"`), or resets it (`"reset"`: a close with no linger,
    which sends an RST). It writes down everything it is sent."""

    def __init__(self, port, how):
        self.how, self.held = how, []
        super().__init__(port, None)

    def _loop(self):
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            c.settimeout(2)
            try:
                self.seen.append(c.recv(65536))
            except OSError:
                pass
            if self.how == "hold":
                self.held.append(c)
                continue
            if self.how == "reset":
                c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
            c.close()

    def close(self):
        try:
            super().close()
        finally:                                # a stop that raises still lets go of what it holds
            for c in self.held:
                c.close()


def silent_message(port, seconds=None):
    """What a command says when nothing answered: `seconds` only for a timeout, which has waited."""
    when = f" within {seconds:g} s" if seconds else ""
    return f"the sheaf hub on 127.0.0.1:{port} did not answer{when}; try again, or run `sheaf restart`"


def holds_number(text, n):
    """Whether `n` stands alone in `text`: not inside a longer number (`2600`), a word or hex id
    (`c8cd260c`), or a decimal or unit (`260.5`, `260px`)."""
    return bool(re.search(rf"(?<![\w.]){n}(?![\w.])", text))
