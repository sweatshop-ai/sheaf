"""A caller that closes its connection while the hub still builds the answer, over a real socket: the run ends and the
refusal it was owed is dropped quietly (a reload during a slow listing, SPEC 8.6). The handler's own stop is tested in
memory in test_hub_sheaf.py."""
import socket
import struct
import threading
import time
from http.server import ThreadingHTTPServer

from sheafmd.hub import server
from sheafmd.hub.handler import Response


class Slow:
    """A handler that builds its answer page by page and asks `gone()` between pages, as the Sheaf listing does."""
    def __init__(self):
        self.pages, self.started, self.ended = 0, threading.Event(), threading.Event()

    def handle(self, method, target, headers, body=b"", conn=None, via="port", gone=None):
        self.started.set()
        try:
            for _ in range(200):
                if gone():
                    return Response(499, {"Content-Type": "application/json"}, b'{"ok": false, "error": "gone"}')
                self.pages += 1
                time.sleep(0.02)
            return Response(200, {"Content-Type": "application/json"}, b"{}")
        finally:
            self.ended.set()


def test_a_caller_that_closes_the_connection_ends_the_run_and_logs_no_broken_pipe():
    slow, errors = Slow(), []

    class Quiet(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            import sys
            errors.append(sys.exc_info()[1])
    wired = {"handler": slow, "stopping": threading.Event(), "closing": threading.Event()}
    httpd = Quiet(("127.0.0.1", 0), type("Http", (server._Http,), wired))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        c = socket.create_connection(httpd.server_address)
        c.sendall(b"GET /_/mount?sheaf=1 HTTP/1.1\r\nHost: x\r\n\r\n")
        assert slow.started.wait(5)
        time.sleep(0.1)
        c.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))   # close with a reset, as a browser does
        c.close()
        assert slow.ended.wait(3), "the handler kept running for a caller that is gone"
        assert slow.pages < 20, slow.pages
        time.sleep(0.2)
        assert errors == [], errors
    finally:
        httpd.shutdown()
        httpd.server_close()
