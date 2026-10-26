"""The fake listeners of the suite (a stranger, an impostor, a silent port, a session's socket)
must stop listening when they are closed. `socket.close()` from one thread does not end an
`accept()` that another thread is blocked in: the kernel socket stays in LISTEN, takes the next
connect, and its thread never ends. The stall dumps of two CI jobs held 100 thread
stacks, about half of them such threads."""
import ctypes
import socket
import sys
import threading
import time

import pytest

from agent_fakes import Peer
from helpers import Impostor, Silent, stop_listener, stranger
from test_mcp_stdio import stranger as mcp_stranger
from test_remote_box import Forwarder


def tcp_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def refused(address):
    family = socket.AF_UNIX if isinstance(address, str) else socket.AF_INET
    c = socket.socket(family)
    c.settimeout(2)
    try:
        c.connect(address)
    except ConnectionRefusedError:
        return True
    except OSError:
        return False
    finally:
        c.close()
    return False


def made_stranger(tmp_path):
    port = tcp_port()
    s = stranger(port)
    return ("127.0.0.1", port), s.close, s.thread


def made_mcp_stranger(tmp_path):
    port = tcp_port()
    s, _ = mcp_stranger(port)
    return ("127.0.0.1", port), s.close, s.thread


def made_impostor(tmp_path):
    port = tcp_port()
    fake = Impostor(port, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
    return ("127.0.0.1", port), fake.close, fake.thread


def made_silent(how):
    def make(tmp_path):
        port = tcp_port()
        fake = Silent(port, how)
        return ("127.0.0.1", port), fake.close, fake.thread
    return make


def made_peer(tmp_path):
    p = Peer(str(tmp_path / "s.sock"))
    return str(tmp_path / "s.sock"), p.close, p.thread


def made_forwarder(tmp_path):
    f = Forwarder(tcp_port())
    return ("127.0.0.1", f.port), f.close, f.thread


MAKERS = [made_stranger, made_mcp_stranger, made_impostor, made_silent("hold"), made_silent("close"),
          made_silent("reset"), made_peer, made_forwarder]


@pytest.mark.skipif(sys.platform != "linux", reason="shutdown() of a listening socket wakes accept() on Linux only")
@pytest.mark.parametrize("make", MAKERS, ids=lambda m: getattr(m, "__qualname__", str(m)))
def test_a_closed_fake_listener_refuses_the_next_connect_and_its_thread_is_gone(make, tmp_path):
    address, close, thread = make(tmp_path)
    c = socket.socket(socket.AF_UNIX if isinstance(address, str) else socket.AF_INET)
    c.settimeout(2)
    c.connect(address)                       # it listens while it is open
    c.close()
    time.sleep(0.3)                          # the thread is back in accept(): the state close() must end
    close()
    assert refused(address), "a connect after close() was still taken: the port stays in LISTEN"
    assert not thread.is_alive(), "the accept thread outlived close()"
    assert thread not in threading.enumerate()


_libc = ctypes.CDLL(None, use_errno=True) if sys.platform == "linux" else None
if _libc is not None:
    _libc.accept.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]


class HeldPeer(Peer):
    """A `Peer` whose accept thread has read its fd and is held before the `accept` syscall until
    `release` is set: where a thread preempted between the load of its fd and the syscall stands."""

    def __init__(self, path):
        self.held, self.release = threading.Event(), threading.Event()
        super().__init__(path)

    def _serve(self):
        fd = self.srv.fileno()
        self.held.set()
        self.release.wait(30)
        n = _libc.accept(fd, None, None)
        if n < 0:
            return
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, fileno=n)
        self.accepted += 1
        data = b""
        with conn:
            while chunk := conn.recv(65536):
                data += chunk
        with self._cond:
            self.messages.append(data)
            self._cond.notify_all()


@pytest.mark.skipif(sys.platform != "linux", reason="shutdown of a listening socket wakes accept on Linux")
def test_an_accept_thread_that_outlives_the_stop_cannot_take_a_later_listeners_connection(tmp_path):
    """The kernel resolves `accept(fd)` when the syscall is entered, so a thread
    that read its fd before `close()` and enters the syscall after the next `Peer` took the same number
    accepts on that one. A stop whose join runs out must not free the number, and must say so."""
    first = HeldPeer(tmp_path / "a.sock")
    assert first.held.wait(5)
    fd = first.srv.fileno()
    with pytest.raises(AssertionError, match="still running"):
        stop_listener(first.srv, first.thread, timeout=0.3)
    second = Peer(tmp_path / "b.sock")
    try:
        assert second.srv.fileno() != fd, "the stopped listener's descriptor number was handed to the next one"

        def send(data):
            c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            c.connect(str(tmp_path / "b.sock"))
            c.sendall(data)
            c.close()

        first.release.set()                       # the stale thread now enters accept(fd)
        first.thread.join(5)
        assert not first.thread.is_alive()
        for data in (b"one", b"two", b"three"):
            send(data)
        assert second.wait_for(3, timeout=3) == [b"one", b"two", b"three"]
        assert first.accepted == 0
    finally:
        first.release.set()
        first.thread.join(5)
        stop_listener(first.srv, first.thread)    # the thread is gone: this one closes
        second.close()
