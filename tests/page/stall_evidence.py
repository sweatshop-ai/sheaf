"""What a page test that stalled leaves behind for the next person: the page journal, the hub's side and every stack.

Ticket 173 O: on a macOS runner a page stopped answering (PageStalled), then the next test's `new_page()` timed out in
the Playwright driver and the run ended (tests/driver_stall.py). The log held no journal: `stream_journal` reads it with
`page.evaluate`, which goes through the driver that had stopped. So the evidence here takes no road through Playwright:

  * the pages, over a second connection to Chromium's own DevTools port (`--remote-debugging-port`, which Playwright
    leaves free beside its pipe): the list of targets (an HTTP GET to the browser process), then for each page its URL,
    `window.__sseJournal`, `__leaving` and `__same_load`, read with Runtime.evaluate. Each step has a bound of its own, and
    what does not answer says so, which tells a frozen driver (the pages answer) from a frozen browser (the list does not)
    from a frozen renderer (the list answers, the page does not);
  * the hub's side: the test's `hub_journal` (the hub runs on a thread of this process), and the diagnostics and write
    logs under the test's home;
  * the stack of every thread and of every greenlet (the test's own waits on a greenlet that a thread dump does not show),
    and the processes under this one with their state (the driver, the browser and its children).

It is kept only where SHEAF_STALL_EVIDENCE names a folder (CI sets it and uploads the folder when the job fails); with it
unset Chromium opens no port and nothing is written. One folder per test and phase."""
import base64
import faulthandler
import gc
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from pathlib import Path

from pagehelp import PageStalled

ENV = "SHEAF_STALL_EVIDENCE"
ASK_BOUND = 5.0          # seconds one question to the browser may take before it counts as not answering
PAGE_JS = ("JSON.stringify({url: location.href, leaving: window.__leaving === true, sameLoad: window.__same_load === true, "
           "journal: window.__sseJournal || null})")

_port = None             # the DevTools port of the session's Chromium, once `launch_args` gave it one


def folder():
    """The folder the evidence goes to, or None when none is kept."""
    where = os.environ.get(ENV, "").strip()
    return Path(where) if where else None


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def launch_args():
    """The arguments the session's Chromium gets: a DevTools port of its own on 127.0.0.1 when evidence is kept."""
    global _port
    if folder() is None:
        return []
    _port = free_port()
    return [f"--remote-debugging-port={_port}"]


# ── a DevTools client with no Playwright in it ─────────────────────────────────────────────────────────────

def targets(port, bound=ASK_BOUND):
    """The browser's targets (`/json/list`), answered by the browser process itself."""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=bound) as r:
        return json.loads(r.read().decode())


class _Socket:
    """The few bytes of RFC 6455 that one Runtime.evaluate needs: a client's masked text frame out, frames in."""

    def __init__(self, ws_url, bound):
        m = re.match(r"ws://([^/:]+):(\d+)(/.*)", ws_url)
        if not m:
            raise ValueError(f"not a DevTools address: {ws_url}")
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=bound)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            got = self.sock.recv(4096)
            if not got:
                raise ConnectionError("the browser closed the connection before its handshake")
            head += got
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"the browser refused the connection: {status.decode(errors='replace')}")
        self.rest = head.split(b"\r\n\r\n", 1)[1]

    def _exactly(self, n):
        while len(self.rest) < n:
            got = self.sock.recv(65536)
            if not got:
                raise ConnectionError("the browser closed the connection")
            self.rest += got
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, text):
        data = text.encode()
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def receive(self):
        message = b""
        while True:
            b0, b1 = self._exactly(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._exactly(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exactly(8))[0]
            payload = self._exactly(n)          # a server's frames are not masked
            op = b0 & 0x0F
            if op in (0x9, 0xA):                # ping, pong: not ours to answer for one question
                continue
            if op == 0x8:
                raise ConnectionError("the browser closed the connection")
            message += payload
            if b0 & 0x80:
                return message.decode()

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def evaluate(ws_url, expression, bound=ASK_BOUND):
    """The value of `expression` in the page of `ws_url`, over a connection of its own. A renderer that does not run
    the script within `bound` raises (socket.timeout)."""
    s = _Socket(ws_url, bound)
    try:
        s.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                           "params": {"expression": expression, "returnByValue": True}}))
        while True:
            answer = json.loads(s.receive())
            if answer.get("id") == 1:
                break
    finally:
        s.close()
    if "error" in answer:
        raise RuntimeError(answer["error"].get("message", str(answer["error"])))
    result = answer["result"]
    if "exceptionDetails" in result:
        raise RuntimeError(result["exceptionDetails"].get("text", "the script threw"))
    return result["result"].get("value")


def pages_report(port):
    """Each page of the browser behind `port`: its URL, its flags and its stream journal, or why it could not be read."""
    if port is None:
        return f"no DevTools port: the session's Chromium was launched without one ({ENV} was unset then)\n"
    began = time.monotonic()
    try:
        listed = targets(port)
    except Exception as e:
        return (f"the browser process did not list its targets in {ASK_BOUND:.0f} s: {type(e).__name__}: {e}\n"
                "(the browser itself does not answer, not only the Playwright driver)\n")
    out = [f"the browser listed {len(listed)} target(s) in {time.monotonic() - began:.2f} s"]
    for t in listed:
        out.append(f"\n== {t.get('type')} {t.get('url')} ({t.get('title', '')[:60]})")
        if t.get("type") != "page" or not t.get("webSocketDebuggerUrl"):
            continue
        began = time.monotonic()
        try:
            got = json.loads(evaluate(t["webSocketDebuggerUrl"], PAGE_JS))
        except Exception as e:
            out.append(f"   the page did not answer in {ASK_BOUND:.0f} s: {type(e).__name__}: {e} (its renderer is busy or gone)")
            continue
        out.append(f"   answered in {time.monotonic() - began:.2f} s; leaving={got['leaving']} sameLoad={got['sameLoad']}")
        for at, what, data in got["journal"] or []:
            out.append(f"   {clock(at / 1000)} {what} {data}")
        if not got["journal"]:
            out.append("   (no stream journal on this page)")
    return "\n".join(out) + "\n"


# ── this process ───────────────────────────────────────────────────────────────────────────────────────────

def clock(t):
    return f"{time.strftime('%H:%M:%S', time.localtime(t))}.{int(t * 1000) % 1000:03d}"


def stacks():
    """Every thread's stack, with its name, then every greenlet's that is parked (the test's own, the driver's dispatcher)."""
    names = {t.ident: t.name for t in threading.enumerate()}
    out = []
    for ident, frame in sys._current_frames().items():
        out.append(f"--- thread {names.get(ident, '?')} ({ident})\n" + "".join(traceback.format_stack(frame)))
    try:
        import greenlet
    except ImportError:
        return "\n".join(out)
    for g in [o for o in gc.get_objects() if isinstance(o, greenlet.greenlet)]:
        if g.gr_frame is not None:
            out.append(f"--- greenlet {g!r}\n" + "".join(traceback.format_stack(g.gr_frame)))
    return "\n".join(out)


def processes():
    """The processes under this one (the driver, the browser and its children), with their state, from `ps`."""
    try:
        r = subprocess.run(["ps", "-axwwo", "pid,ppid,stat,etime,pcpu,rss,command"], capture_output=True, text=True, timeout=20)
    except Exception as e:
        return f"ps did not run: {e}\n"
    rows = r.stdout.splitlines()
    parent = {}
    for row in rows[1:]:
        f = row.split(None, 2)
        if len(f) > 1 and f[0].isdigit() and f[1].isdigit():
            parent[int(f[0])] = int(f[1])
    mine = {os.getpid()}
    grew = True
    while grew:
        more = {p for p, pp in parent.items() if pp in mine} - mine
        mine |= more
        grew = bool(more)
    return "\n".join(rows[:1] + [row for row in rows[1:] if row.split(None, 1)[0].isdigit()
                                  and int(row.split(None, 1)[0]) in mine]) + "\n"


def hub_report(journal):
    return "\n".join(f"{clock(t)} {what}" for t, what in journal or []) + "\n" if journal else "(no hub journal)\n"


def _safe(name):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:150]


def _write(path, make):
    """One file of the evidence. A part that fails says why in its file and leaves the others."""
    try:
        text = make()
    except (Exception, PageStalled) as e:      # a PageStalled too: this is the last word of a test that already failed
        text = f"could not be read: {type(e).__name__}: {e}\n"
    path.write_text(text, encoding="utf-8", errors="replace")


def save(nodeid, when, why, hub_journal=None, port=None, into=None):
    """Write the evidence of one stalled phase; the folder written, or None when none is kept.
    The pages are read on a thread of their own and waited for a bounded time, so this returns even if the browser
    holds a connection open without answering."""
    root = into or folder()
    if root is None:
        return None
    port = _port if port is None else port
    where = Path(root) / f"{_safe(nodeid)}-{when}-{os.getpid()}-{int(time.time())}"
    where.mkdir(parents=True, exist_ok=True)
    (where / "why.txt").write_text(f"{nodeid} ({when}) at {clock(time.time())}\n\n{why}\n", encoding="utf-8")
    _write(where / "stacks.txt", stacks)
    with open(where / "stacks-faulthandler.txt", "w") as f:       # the C-level view, should a thread hold no Python frame
        faulthandler.dump_traceback(file=f, all_threads=True)
    _write(where / "hub-journal.txt", lambda: hub_report(hub_journal))
    _copy_hub_logs(where)
    reader = threading.Thread(target=_write, args=(where / "pages.txt", lambda: pages_report(port)),
                              name="stall-evidence-pages", daemon=True)
    reader.start()
    _write(where / "processes.txt", processes)
    reader.join(ASK_BOUND * 2 + 10)
    if reader.is_alive():
        (where / "pages.txt").write_text("the pages were still being read when the evidence was closed\n", encoding="utf-8")
    return where


def _copy_hub_logs(where):
    """The hub's own logs under the test's home: its diagnostics (hub-start, peer-check-off, unclean exit) and its writes."""
    try:
        from sheafmd import diagnostics
        from sheafmd.hub import writelog
        logs = [diagnostics.log_path(), writelog.log_path()]
    except Exception as e:
        (where / "hub-logs.txt").write_text(f"the hub's log paths could not be found: {e}\n", encoding="utf-8")
        return
    for log in logs:
        try:
            if log.exists():
                shutil.copyfile(log, where / f"hub-{log.name}")
        except OSError as e:
            (where / f"hub-{log.name}.txt").write_text(f"not copied: {e}\n", encoding="utf-8")
