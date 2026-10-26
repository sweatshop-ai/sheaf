"""The hub's own socket, `<runtime>/hub-<port>.sock` (SPEC 11.4, D16).

It exists so that the `from` address of a Tell message is a place a session can send to. What a
session sends there is written to the diagnostics log and does nothing else: no comment, no push
into any session. Every test runs the hub in this process, on a free port, in the test's own
runtime folder."""
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from helpers import PLAN
from sheafmd import diagnostics, paths
from sheafmd.hub import server
from sheafmd.hub.core import Hub
from sheafmd.hub.sock import MAX_READ


@pytest.fixture
def hubsrv(work):
    """(hub, server, port): a running hub that is closed when the test ends."""
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    yield hub, srv, port
    srv.close()


def send(path, data: bytes):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect(str(path))
        s.sendall(data)
        s.shutdown(socket.SHUT_WR)
        s.recv(1)                           # the hub closes the connection: it answers nothing
    finally:
        s.close()


def rows(kind):
    return [r for r in diagnostics.read() if r["kind"] == kind]


def wait_for_rows(kind, n=1, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        got = rows(kind)
        if len(got) >= n:
            return got
        time.sleep(0.02)
    raise AssertionError(f"{len(rows(kind))} row(s) of {kind}, wanted {n}")


def test_the_hub_listens_on_its_own_socket_readable_by_nobody_else(hubsrv):
    hub, srv, port = hubsrv
    p = paths.hub_socket(port)
    st = os.lstat(p)
    assert stat.S_ISSOCK(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600
    assert st.st_uid == os.getuid()
    assert stat.S_IMODE(os.lstat(p.parent).st_mode) == 0o700


def test_the_address_a_tell_comes_from_is_this_socket(hubsrv):
    hub, srv, port = hubsrv
    assert hub.sender == f"uds:{paths.hub_socket(port)}"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.connect(hub.sender.removeprefix("uds:"))
    finally:
        s.close()


def test_what_a_session_sends_is_logged_as_tell_socket_message_and_nothing_else_happens(hubsrv, work):
    hub, srv, port = hubsrv
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    before = f.read_bytes()
    asked = []
    hub.adapter = lambda agent: asked.append(agent)       # a push, were there one, would ask for this
    send(paths.hub_socket(port), b'{"type":"user","message":{"content":"Done, see the comment"}}\n')
    (row,) = wait_for_rows("tell-socket-message")
    assert row["source"] == "hub" and "Done, see the comment" in row["message"]
    time.sleep(0.2)
    assert f.read_bytes() == before and asked == []
    assert hub.jobs() == {"asking": [], "telling": []}


def test_a_message_is_clipped_to_2000_characters(hubsrv):
    hub, srv, port = hubsrv
    send(paths.hub_socket(port), b"x" * 5000)
    (row,) = wait_for_rows("tell-socket-message")
    assert row["message"] == "x" * 2000 + "…"


def test_a_sender_that_never_stops_is_cut_off_and_one_row_is_written(hubsrv):
    hub, srv, port = hubsrv
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(str(paths.hub_socket(port)))
    try:
        sent = 0
        try:
            while sent < 50 * MAX_READ:
                s.sendall(b"y" * 65536)
                sent += 65536
        except OSError:
            pass                                    # the hub closed on us: that is the cut
        assert sent < 50 * MAX_READ
    finally:
        s.close()
    assert len(wait_for_rows("tell-socket-message")) == 1


def test_bytes_that_are_not_text_are_logged_not_fatal(hubsrv):
    hub, srv, port = hubsrv
    send(paths.hub_socket(port), b"\xff\xfe\x00 not text")
    (row,) = wait_for_rows("tell-socket-message")
    assert "not text" in row["message"]
    send(paths.hub_socket(port), b"again")
    assert len(wait_for_rows("tell-socket-message", 2)) == 2


def test_a_connection_that_says_nothing_is_dropped_and_the_next_is_served(hubsrv, monkeypatch):
    hub, srv, port = hubsrv
    mute = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    mute.connect(str(paths.hub_socket(port)))
    try:
        send(paths.hub_socket(port), b"after the silent one")
        (row,) = wait_for_rows("tell-socket-message")
        assert row["message"] == "after the silent one"
    finally:
        mute.close()


def test_the_socket_is_removed_when_the_hub_stops(work):
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    assert paths.hub_socket(port).exists()
    srv.stop("test")
    srv.close()
    assert not paths.hub_socket(port).exists()


def test_a_socket_left_by_a_hub_that_crashed_is_replaced(work):
    sock = server.bind(0)
    port = sock.getsockname()[1]
    p = paths.hub_socket(port)
    paths.private_dir(p.parent)
    old = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old.bind(str(p))
    old.close()                                    # the file stays, nobody listens
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    try:
        send(p, b"hello")
        wait_for_rows("tell-socket-message")
    finally:
        srv.close()


def test_a_file_that_is_not_a_socket_is_never_removed(work):
    sock = server.bind(0)
    port = sock.getsockname()[1]
    p = paths.hub_socket(port)
    paths.private_dir(p.parent)
    p.write_text("precious")
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    try:
        assert p.read_text() == "precious"
        assert rows("tell-socket-failed")
    finally:
        srv.close()
    assert p.read_text() == "precious"


def test_a_path_too_long_for_a_socket_costs_the_hub_nothing(tmp_path, monkeypatch):
    run = tmp_path / ("r" * 120)
    run.mkdir(mode=0o700)
    monkeypatch.setattr(paths, "runtime_dir", lambda: run / "sheaf")   # macOS ignores XDG_RUNTIME_DIR
    sock = server.bind(0)
    port = sock.getsockname()[1]
    hub = Hub(port=port, key=paths.ensure_key(), started_by="test")
    srv = server.HubServer(hub, sock)
    srv.start()
    try:
        (row,) = wait_for_rows("tell-socket-failed")
        assert row["source"] == "hub" and str(port) in row["path"]
        c = socket.create_connection(("127.0.0.1", port), timeout=5)
        c.sendall(b"GET /_/hub HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        assert c.recv(12).startswith(b"HTTP/1.1 ")      # the hub itself still answers
        c.close()
    finally:
        srv.close()


def test_the_socket_tests_pass_under_a_basetemp_of_125_characters():
    """A socket path holds 108 characters, and a suite run whose --basetemp is long (a branch name in
    it) once made the hub-socket tests fail with `AF_UNIX path too long`: conftest puts the sockets
    under a short folder of its own."""
    outer = Path(tempfile.mkdtemp(prefix="bt-", dir="/tmp"))     # short, whatever the basetemp of this run
    basetemp = outer / ("b" * (125 - len(str(outer)) - 1))
    assert len(str(basetemp)) == 125
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        ran = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--basetemp={basetemp}",
             f"{here}/test_hub_sock.py", "-k", "not 125_characters"],
            capture_output=True, text=True, timeout=120)
    finally:
        shutil.rmtree(outer, ignore_errors=True)
    assert ran.returncode == 0, ran.stdout[-2000:]
