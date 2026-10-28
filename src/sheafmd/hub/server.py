"""
sheafmd.hub.server — the socket, the threads and the lifecycle of the hub (SPEC 8.1, 8.4).

`HubServer` turns the handler's answers into HTTP bytes and the handler's streams into
`text/event-stream`; `run()` is `sheaf hub`: bind, write `hub.pid`, serve until a stop, clean up.

The hub binds 127.0.0.1 only and never tries another port: a port that is taken is a hub that
already runs (or something that is not one), and the command that started this one goes and
asks it (SPEC 9.4).
"""
import errno
import json
import os
import select
import signal
import socket
import socketserver
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import __version__, config, diagnostics, paths
from ..source import STAMP_FORMAT
from . import peer, proxy, sender, state, the_list
from .client import STOPPING
from .core import Hub
from .events import KEEPALIVE, KEEPALIVE_SECONDS, PREAMBLE, frame
from .handler import MAX_BODY, Handler, Refuse
from .sock import TellSocket

TICK_SECONDS = 1.0
WAIT_SLICE = 0.25
ENDS_STREAM = ("hub-stopping", "signed-out", "gone")   # the last event a tab gets on this stream
EXIT_UPGRADE = 75                     # sysexits EX_TEMPFAIL: the service manager starts the new code
IDLE_SECONDS = 60.0              # a connection that is silent for this long, between requests or inside a head, is closed
BODY_SECONDS = 30.0              # all of a body, from the moment the caller has been checked
LINGER_SECONDS = 0.5             # what a refused caller's unread body gets to arrive and be dropped
LINGER_BYTES = 1024 * 1024
_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD")


class PortTaken(Exception):
    pass


def bind(port: int) -> socket.socket:
    """A listening socket on 127.0.0.1:`port`. Raises PortTaken when something holds it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        s.listen(64)
    except OSError as e:
        s.close()
        if e.errno == errno.EADDRINUSE:
            raise PortTaken(port) from None
        raise
    return s


def pid_file():
    return paths.state_dir() / "hub.pid"


def read_pid_file() -> dict | None:
    got = state.read_json(pid_file(), {})
    return got if got.get("pid") else None


class _Http(BaseHTTPRequestHandler):
    """The adapter: bytes in, one `Handler.handle` call, bytes out."""
    protocol_version = "HTTP/1.1"
    server_version = "sheaf"
    sys_version = ""
    handler: Handler = None          # set on the subclass `HubServer` makes
    stopping: threading.Event = None
    closing: threading.Event = None  # set when a stop begins: a kept-alive connection is refused from then on
    served = False                   # whether this connection has already served a request
    via = "port"                     # which listener: the loopback port, or the proxy socket (9.9)

    def log_message(self, *a):
        pass

    def version_string(self):
        return self.server_version

    def setup(self):
        self.timeout = IDLE_SECONDS      # read for each connection, so a test can change it
        super().setup()

    def _serve(self):
        again, self.served = self.served, True
        if again and self.closing.is_set() and not self._is_stop():
            # a connection kept alive past the start of a stop: the hub is about to exit, so nothing
            # more is applied on it; the caller is refused and tries a new connection. A new
            # connection is served until the listener closes, and a stop is always answered, so that
            # the reason of a stop under way keeps its precedence.
            self._refuse(503, STOPPING)
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Length", "0").strip() not in ("", "0"):
                self._linger()
            return
        n = 0
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            pass
        # The body is read only when the handler asks for it, and it asks after the Host, the
        # credential and the Origin are checked: a caller that is refused costs no thread, no
        # memory and no wait for a body. A body over the limit is never read either; the handler
        # refuses it by its header. Whatever was not read ends the connection. A body sent in
        # chunks is never one the hub takes (it reads Content-Length bytes), so there is nothing
        # to skip over: what follows its head must not be read as the next request.
        chunked = bool(self.headers.get("Transfer-Encoding"))
        asked = []

        def body() -> bytes:
            asked.append(True)
            return self._read_body(n) if 0 < n <= MAX_BODY else b""

        res = self.handler.handle(self.command, self.path, dict(self.headers.items()), body,
                                  conn=self._conn(), via=self.via)
        unread = (n != 0 and not asked) or chunked
        if unread or n < 0 or n > MAX_BODY:
            self.close_connection = True
        if res.stream is not None:
            self._stream(res)
            return
        self.send_response(res.status)
        for k, v in res.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(res.body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD" and res.body and res.status not in (204, 304):
            self.wfile.write(res.body)
        if unread and (n > 0 or chunked):
            self._linger()

    def _is_stop(self) -> bool:
        return self.command == "POST" and self.path.split("?", 1)[0] == "/_/stop"

    def _conn(self):
        """The connection, as the handler judges who is at its other end."""
        return peer.Conn(self.client_address[:2], self.connection.getsockname()[:2])

    def _read_body(self, n: int) -> bytes:
        """`n` bytes within BODY_SECONDS in all: a read that is fed a byte at a time still ends."""
        end, out = time.monotonic() + BODY_SECONDS, bytearray()
        try:
            while len(out) < n:
                left = end - time.monotonic()
                if left <= 0:
                    raise TimeoutError
                self.connection.settimeout(left)
                chunk = self.rfile.read1(min(n - len(out), 65536))
                if not chunk:
                    break
                out += chunk
        except OSError:                  # TimeoutError is one; the read side is no good after it
            self.close_connection = True
            raise Refuse(408, "the request body did not arrive in time") from None
        self.connection.settimeout(IDLE_SECONDS)
        return bytes(out)

    def _linger(self):
        """The caller was refused before its body was read. Let what it has already sent arrive
        and drop it, so that closing sends a FIN and not a reset that could take the answer
        with it. Short, and bounded in bytes."""
        try:
            self.connection.shutdown(socket.SHUT_WR)
            end, got = time.monotonic() + LINGER_SECONDS, 0
            while got < LINGER_BYTES and (left := end - time.monotonic()) > 0:
                if not select.select([self.connection], [], [], left)[0]:
                    break
                chunk = self.connection.recv(65536)
                if not chunk:
                    break
                got += len(chunk)
        except OSError:
            pass

    def _stream(self, res):
        """Held open for the life of the tab. Watching the read side is what makes a closed tab
        register within a second: waiting for the next write to fail takes up to two
        keepalives, because the first write after a close still lands in the kernel buffer."""
        sub = res.stream
        self.close_connection = True
        try:
            self.send_response(res.status)
            for k, v in res.headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(PREAMBLE)
            due = time.time() + KEEPALIVE_SECONDS
            ends = self._stream_ends()
            while True:
                for name, data in sub.drain():
                    self.wfile.write(frame(name, data))
                    if name in ENDS_STREAM:
                        self.wfile.flush()
                        return
                self.wfile.flush()
                if self.stopping.is_set() or (ends is not None and time.monotonic() >= ends):
                    return
                if time.time() >= due:
                    self.wfile.write(KEEPALIVE)
                    self.wfile.flush()
                    due = time.time() + KEEPALIVE_SECONDS
                if select.select([self.connection], [], [], 0)[0] and \
                        not self.connection.recv(1, socket.MSG_PEEK):
                    return
                got = sub.get(timeout=0.25)
                if got is not None:
                    self.wfile.write(frame(*got))
                    if got[0] in ENDS_STREAM:
                        self.wfile.flush()
                        return
        except (OSError, ValueError):
            pass
        finally:
            sub.close()

    def _stream_ends(self):
        """When the stream is closed whatever happens on it (time.monotonic), or None: never."""
        return None

    def send_error(self, code, message=None, explain=None):
        """What http.server itself refuses (a request it cannot parse) is JSON like every other
        refusal, never its HTML page, which would carry no policy."""
        self._refuse(code, f"bad request ({code})")

    def _refuse(self, code: int, error: str):
        """An answer that is JSON, carries no page and ends the connection."""
        body = json.dumps({"ok": False, "error": error}).encode()
        try:
            self.send_response(code)
            for k, v in (("Content-Type", "application/json"), ("Cache-Control", "no-store"),
                         ("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"),
                         ("Content-Length", str(len(body))), ("Connection", "close")):
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except OSError:
            pass
        self.close_connection = True


for _m in _METHODS:
    setattr(_Http, f"do_{_m}", _Http._serve)


class _ProxyHttp(_Http):
    """The proxy socket (SPEC 9.9): the same bytes, judged by the uid at the other end of the
    connection and the member header, and a stream that ends after STREAM_SECONDS, so that a
    session the front has ended loses its streams (the page reconnects through the verifier)."""
    via = "proxy"

    def _conn(self):
        try:
            return proxy.peer(self.connection)
        except OSError:
            return None                  # no uid to read: the handler refuses it as another account's

    def _stream_ends(self):
        return time.monotonic() + proxy.STREAM_SECONDS


class _UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True


class HubServer:
    """The hub on a socket: an HTTP server thread and the watcher thread, and in proxy mode a
    second HTTP server thread on the proxy socket (`proxy_sock`, from `proxy.bind`)."""

    def __init__(self, hub: Hub, sock: socket.socket, proxy_sock: tuple | None = None):
        self.hub, self.sock = hub, sock
        self.stopping = threading.Event()
        self.closing = threading.Event()
        shared = Handler(hub)
        wired = {"handler": shared, "stopping": self.stopping, "closing": self.closing}
        handler = type("Http", (_Http,), wired)
        self.httpd = ThreadingHTTPServer(sock.getsockname(), handler, bind_and_activate=False)
        self.httpd.socket = sock
        self.httpd.daemon_threads = True
        self.proxyd, self._proxy_made = None, None
        if proxy_sock is not None:
            listener, self._proxy_made = proxy_sock
            handler = type("ProxyHttp", (_ProxyHttp,), wired)
            self.proxyd = _UnixServer(str(hub.proxy.socket), handler, bind_and_activate=False)
            self.proxyd.socket = listener
        self._threads: list[threading.Thread] = []
        self._begun = threading.Event()   # a stop has started; `stop` runs once
        hub.on_stop = self._on_stop
        self.done = threading.Event()
        self.crash: str | None = None
        self.tell_socket = TellSocket(hub.port)

    def start(self):
        self.tell_socket.start()
        targets = [self._serve, self._watch]
        if self.proxyd is not None:
            targets.append(lambda: self._serve(self.proxyd))
        for target in targets:
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def _serve(self, httpd=None):
        try:
            (httpd or self.httpd).serve_forever(poll_interval=0.1)
        except BaseException:
            # An exception that escapes the server loop is the hub crashing (SPEC 8.4).
            self.crash = traceback.format_exc()
            self.done.set()

    def _watch(self):
        while not self.stopping.wait(TICK_SECONDS):
            self.hub.tick()

    def _on_stop(self, reason: str):
        """A stop was accepted: kept connections are refused from this moment, not from when the
        worker thread gets to run."""
        self.closing.set()
        threading.Thread(target=self.stop, args=(reason,), daemon=True).start()

    def stop(self, reason: str = "stop"):
        """A clean stop: tell every stream, then stop serving."""
        if self.stopping.is_set() or self._begun.is_set():
            return
        self._begun.set()
        self.closing.set()                # first: from here no kept-alive connection is served
        self.hub.announce_stop(reason)
        self.hub.stop_jobs()
        time.sleep(0.15)                  # let the streams write it before the server goes
        self.tell_socket.stop()
        if self.hub.the_list is not None:
            self.hub.the_list.stop()
        self.stopping.set()
        self.httpd.shutdown()
        self.httpd.server_close()         # shutdown leaves the port listening; close gives it back
        self._close_proxy()
        self.done.set()

    def close(self):
        self.closing.set()
        self.hub.stop_jobs()
        self.tell_socket.stop()
        if self.hub.the_list is not None:
            self.hub.the_list.stop()
        if not self.stopping.is_set():
            self.stopping.set()
            self.httpd.shutdown()
        self.httpd.server_close()
        self._close_proxy()
        self.done.set()

    def _close_proxy(self):
        """Stop serving the proxy socket and remove its file, if it is still the one made at start."""
        proxyd, self.proxyd = self.proxyd, None
        if proxyd is not None:
            proxyd.shutdown()
            proxyd.server_close()
            proxy.unlink(self.hub.proxy, self._proxy_made)

    def wait(self):
        # Never a bare wait: the kernel may hand a SIGTERM to any thread, and a main thread
        # blocked on a plain lock is not woken to run its handler. A short timeout is.
        while not self.done.wait(WAIT_SLICE):
            pass


# ── `sheaf hub` ──────────────────────────────────────────────────────────────

def note_unclean_exit(port: int):
    """A hub that ended without a word (kill -9, a power cut) leaves a hub-start with no hub-exit
    of the same boot. The next hub that holds the port says so, once, before its own hub-start.
    Called only after the bind: the winner of a race has a hub-start and no exit because it is
    running, and the loser must never call that unclean."""
    last, closed = None, set()
    for r in diagnostics.read():
        if r.get("source") != "hub":
            continue
        if r.get("kind") == "hub-start":
            last = r
        elif r.get("kind") == "hub-exit":
            closed.add(r.get("boot"))
    if last and last.get("boot") not in closed:
        diagnostics.record("hub", "unclean-exit", None, boot=last.get("boot"), port=port,
                           started=last.get("at"), was_version=last.get("version"))


def exit_code(hub: Hub) -> int:
    """What a hub that was asked to stop exits with. An upgrade stop under the service ends with a
    code that is a failure to the service manager, so Restart=on-failure and
    KeepAlive.SuccessfulExit=false start the new code (14.4). A restart the service manager itself
    asked for (`told_restart`) is not a failure to it, and a stop that is not an upgrade ends the hub."""
    reason = hub.stop_requested or "stop"
    return EXIT_UPGRADE if reason == "upgrade" and hub.service and not hub.told_restart else 0


def _proxy_refused(e: "proxy.ProxyError") -> int:
    diagnostics.record("hub", "proxy-config", None, reason=str(e))
    print(f"sheaf hub: {e}", file=sys.stderr)
    return 1


def _list_refused(e: "the_list.ListError") -> int:
    diagnostics.record("hub", "list-config", None, reason=str(e))
    print(f"sheaf hub: {e}", file=sys.stderr)
    return 1


def run(started_by: str = "cli") -> int:
    """Run the hub in the foreground. Exit 0 after a clean stop, 1 when the port is taken or
    the hub crashed, 75 after an upgrade stop of a hub the service started (SPEC 8.4, 14.4).
    Where the OS gives siginfo, SIGTERM and SIGINT are blocked from here on in every thread and
    one thread takes them, so that the exit row can say who sent the signal (`sender`)."""
    signals = sender.Signals()           # before any thread of the hub, which would inherit the mask
    try:
        return _run(started_by, signals)
    finally:
        signals.close()


def _run(started_by: str, signals: "sender.Signals") -> int:
    # The port listens from the bind on, so a command may ask the hub to stop from that instant.
    # The handler is therefore the first thing: a stop asked for before the hub exists is applied
    # the moment it does, and a hub that has written a row never dies without writing its exit.
    hub_cell: dict = {}                   # holds the hub from the moment it exists
    signals_before_the_hub: list = []
    signal_row: dict = {}                 # the first signal: its name and, where the OS says, its sender

    def on_signal(signum, frame_, fields=None):
        if not signal_row:
            signal_row.update(fields or {"signal": sender.name(signum)})
        if "hub" in hub_cell:
            hub_cell["hub"].request_stop("signal")
        else:
            signals_before_the_hub.append(signum)

    # The ordinary handler stays: it takes a signal that reaches a thread the hub did not make
    # (a test that runs the hub in its own process), and where there is no siginfo it takes all.
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    signals.start(lambda signum, fields: on_signal(signum, None, fields))
    port = config.port()
    # Proxy mode is checked whole before the port is bound, and its socket is bound after the port:
    # binding the port is the lock between two hubs, so a second hub fails on `port-taken`, not on
    # the socket the first one holds. The hub never runs with part of the mode (9.9).
    try:
        cfg = proxy.load()
        if cfg is not None:
            proxy.check_names(cfg, config.user_name(), [t.display for t in state.Tokens().list()])
            proxy.check_folder(cfg)
    except proxy.ProxyError as e:
        return _proxy_refused(e)
    # The list (9.10) is checked with it, and needs it: the list is a member's page.
    try:
        list_cfg = the_list.load()
        if list_cfg is not None and cfg is None:
            raise the_list.ListError(f"[list] of {paths.config_file()} needs a [proxy] table: the list is a member's page")
        for key in the_list.FOLDER_KEYS if list_cfg is not None else ():
            # A file dropped in a member's root would be a document they open; a transcript there, one they read.
            folder = getattr(list_cfg, key)
            for m in cfg.members.values() if folder is not None else ():
                if any(the_list._within(str(folder), r) for r in m.roots):
                    raise the_list.ListError(f"'{key}' of [list] of {paths.config_file()} is inside a root of "
                                             f"{m.name}: {folder}")
    except the_list.ListError as e:
        return _list_refused(e)
    # From reading the key to holding the port, `sheaf rotate` on a machine with no hub waits: it
    # must not replace the key of a hub that is a moment from listening on the old one.
    with paths.key_lock():
        key = paths.ensure_key()
        try:
            sock = bind(port)
        except PortTaken:
            # Binding is the lock: a hub that lost the race writes only this row, never hub-start.
            diagnostics.record("hub", "port-taken", None, port=port, started_by=started_by)
            print(f"sheaf hub: 127.0.0.1:{port} is already in use", file=sys.stderr)
            return 1
    proxy_sock = None
    if cfg is not None:
        try:
            proxy_sock = proxy.bind(cfg)
        except proxy.ProxyError as e:
            sock.close()
            return _proxy_refused(e)
    hub = Hub(port=port, key=key, started_by=started_by, service=started_by == "service", proxy=cfg)
    srv = HubServer(hub, sock, proxy_sock)
    if list_cfg is not None:
        hub.the_list = the_list.TheList(hub, list_cfg)
        hub.the_list.start()
    hub_cell["hub"] = hub
    if signals_before_the_hub:
        hub.request_stop("signal")
    note_unclean_exit(port)
    state.write_json(pid_file(), {"pid": os.getpid(), "boot": hub.boot, "port": port,
                                  "version": __version__, "started": time.strftime(STAMP_FORMAT),
                                  "service": hub.service})
    diagnostics.record("hub", "hub-start", None, version=__version__, started_by=started_by,
                       port=port, boot=hub.boot)
    try:
        srv.start()
        srv.wait()
    finally:
        srv.close()
        try:
            if (read_pid_file() or {}).get("pid") == os.getpid():
                pid_file().unlink()
        except OSError:
            pass
    if srv.crash:
        diagnostics.record("hub", "hub-exit", None, reason="crash", boot=hub.boot,
                           traceback=srv.crash[-1900:])
        return 1
    reason = hub.stop_requested or "stop"
    diagnostics.record("hub", "hub-exit", None, reason=reason, boot=hub.boot,
                       **(signal_row if reason == "signal" else {}))
    return exit_code(hub)
