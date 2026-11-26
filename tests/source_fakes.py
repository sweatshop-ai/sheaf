"""The reference Source service as a separate process, and a stand-in that answers what a test tells it to (ticket 21)."""
import json
import os
import secrets
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

AUTHORS = '[authors]\n"Ada" = "Ada Writer <ada@example.org>"\n"Grace" = "Grace Editor <grace@example.org>"\n'


def short_dir() -> Path:
    """A folder of its own under /tmp: a socket path holds 108 characters, and tmp_path is deeper than that."""
    return Path(tempfile.mkdtemp(prefix="ss-", dir="/tmp"))


class ReferenceService:
    """`python -m sheafmd.sourceservice` over `folder`, listening on a Unix socket in a short folder of its own."""

    def __init__(self, folder: Path, secrets_dir: Path, authors: str = AUTHORS):
        self.folder = Path(folder)
        self.run = short_dir()
        self.sock = str(self.run / "s.sock")
        self.bearer = secrets.token_urlsafe(24)
        self.secrets_file = Path(secrets_dir) / "bearer"
        self.secrets_file.write_text(self.bearer + "\n", encoding="utf-8")
        self.secrets_file.chmod(0o600)
        self.authors_file = Path(secrets_dir) / "authors.toml"
        self.authors_file.write_text(authors, encoding="utf-8")
        self.url = f"unix://{self.sock}"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "sheafmd.sourceservice", "--folder", str(self.folder), "--secrets", str(self.secrets_file),
             "--authors", str(self.authors_file), "--socket", self.sock],
            env={**os.environ, "SHEAF_PORT": os.environ.get("SHEAF_PORT", "1")}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline()
        if line.strip() != "listening":
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc.wait()
            said = self.proc.stderr.read()          # read before `stop` closes the pipe
            self.stop()
            raise AssertionError(f"the reference service did not start: {said}")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        for pipe in (self.proc.stdout, self.proc.stderr):
            if pipe:
                pipe.close()
        shutil.rmtree(self.run, ignore_errors=True)

    def stderr_text(self) -> str:
        """What the process said on stderr: only meaningful once it has been stopped."""
        return ""


class Stand:
    """A service of a test's own, in this process, on a Unix socket: `handler(verb, body, headers)` gives `(status, payload)`,
    or None to hold the connection and answer nothing."""

    def __init__(self, handler, close=False):
        self.run = short_dir()
        self.sock = str(self.run / "f.sock")
        self.url = f"unix://{self.sock}"
        self.seen = []
        stand = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                stand.seen.append((self.path.strip("/"), body, dict(self.headers)))
                got = handler(self.path.strip("/"), body, dict(self.headers))
                if got is None:
                    time.sleep(30)
                    return
                status, payload = got
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                if close:
                    self.send_header("Connection", "close")      # the answer after which the client's socket is let go
                    self.close_connection = True
                self.end_headers()
                self.wfile.write(raw)

        class S(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
        self.server = S(self.sock, H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.run, ignore_errors=True)


def refuses_connections(sock_path: str) -> bool:
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(sock_path)
        return False
    except OSError:
        return True
    finally:
        s.close()
