"""The reference Source service (ADR 0006): a folder of Markdown served over the protocol of `remote.py`.

    python -m sheafmd.sourceservice --folder DIR --secrets FILE --authors FILE (--socket PATH | --port N)

It is a separate process, the template for a service of a real source and the partner the adapter contract suite tests the
remote adapter against. What it holds:

- the folder it serves, and nothing else of a site: it has no key to anything;
- the hub's bearer, in the file named by `--secrets` (one line). A request without it is `unauthorized`, whatever it asks;
- a small table of authors, in the file named by `--authors`:

      [authors]
      "Ada Lovelace" = "Ada Lovelace <ada@example.org>"

  The key is the member as the hub states it in `author`; the value is the name and address of the commit. A member the table
  does not name is refused with `unknown_author` before anything is read or written.

A write goes through the Markdown-file adapter, so its outcomes and its base (the hash of the text) are the file adapter's own.
Where the folder is inside a git work tree, a write that changed the file is committed with the mapped author; the note is the
commit message. The service listens on a Unix socket or on a loopback port, in plain HTTP: TLS, where there is any, is in front of it.
"""
import argparse
import base64
import binascii
import hmac
import json
import os
import re
import socketserver
import stat
import subprocess
import sys
import tomllib
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from . import adapter as rda
from . import source as rds
from .beneath import OWN
from .remote import PAGE_MAX, status_of

BODY_MAX = 16 * 1024 * 1024
_ADDRESS = re.compile(r"\s*([^<>\r\n]+?)\s*<([^<>\s@]+@[^<>\s]+)>\s*")
_TOKEN = re.compile(r"[\x21-\x7e]{16,512}")


class Fault(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def read_bearer(path) -> str:
    """The bearer in the file `path`: one line of printable characters, 16 to 512 of them."""
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.geteuid() or st.st_mode & 0o077:
            raise SystemExit(f"{path}: must be a regular file of this account and readable by it alone (chmod 600)")
        text = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        raise SystemExit(f"{path}: cannot be read ({type(e).__name__})")
    if not _TOKEN.fullmatch(text):
        raise SystemExit(f"{path}: must hold one line, the hub's bearer (16 to 512 printable characters)")
    return text


def read_authors(path) -> dict:
    """`{member: (name, email)}` from the table `[authors]` of the file `path`."""
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SystemExit(f"{path}: cannot be read as TOML ({e})")
    table = data.get("authors", {})
    out = {}
    for member, line in table.items():
        m = _ADDRESS.fullmatch(line) if isinstance(line, str) else None
        if m is None:
            raise SystemExit(f"{path}: the author of {member!r} must be written 'Name <address>'")
        out[member] = (m.group(1), m.group(2))
    return out


def clean_document(name) -> str:
    """The document name as a path below the folder, or `Fault("bad_request")`."""
    if not isinstance(name, str) or not name or "\0" in name or name.startswith("/") or "\\" in name:
        raise Fault("bad_request", "document must be a relative path with / separators")
    parts = name.split("/")
    if any(p in ("", ".", "..") or p in OWN or p.startswith(".") for p in parts) or not rda.MarkdownFileAdapter.accepts(name):
        raise Fault("bad_request", "document must name a .md file below the folder")
    return name


class Service:
    def __init__(self, folder, bearer: str, authors: dict):
        self.top = Path(folder).resolve()
        self._bearer = bearer.encode("utf-8")
        self.authors = authors
        self.git = self._inside_git()

    def authorised(self, header: str | None) -> bool:
        if not header or not header.startswith("Bearer "):
            return False
        # bytes on both sides: compare_digest of text raises for a character that is not ASCII
        return hmac.compare_digest(header[len("Bearer "):].strip().encode("utf-8", "replace"), self._bearer)

    def handle(self, verb: str, body: dict) -> dict:
        if verb == "info":
            return {"interface": rda.INTERFACE_VERSION, "name": self.top.name, "publish": False}
        if verb == "documents":
            return self.documents(body.get("cursor"))
        if verb == "read":
            return self.read(clean_document(body.get("document")))
        if verb == "write":
            return self.write(body)
        raise Fault("bad_request", f"unknown call {verb!r}")

    # ── documents ───────────────────────────────────────────────────────────
    def names(self):
        for dirpath, dirs, files in os.walk(self.top, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not os.path.islink(os.path.join(dirpath, d)))
            here = Path(dirpath).relative_to(self.top)
            for f in files:
                full = os.path.join(dirpath, f)
                if f.endswith(".md") and not f.startswith(".") and not os.path.islink(full) and stat.S_ISREG(os.lstat(full).st_mode):
                    yield (here / f).as_posix()

    def documents(self, cursor) -> dict:
        after = ""
        if cursor is not None:
            try:
                after = base64.b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4), altchars=b"-_", validate=True).decode("utf-8")
            except (AttributeError, UnicodeError, binascii.Error):
                raise Fault("bad_request", "cursor is not one this service gave") from None
        names = sorted(n for n in self.names() if n > after)
        page, more = names[:PAGE_MAX], len(names) > PAGE_MAX
        nxt = base64.urlsafe_b64encode(page[-1].encode("utf-8")).decode("ascii").rstrip("=") if more else None
        return {"documents": [{"name": n} for n in page], "next": nxt}

    # ── read and write ──────────────────────────────────────────────────────
    def adapter(self, rel: str):
        return rda.MarkdownFileAdapter(beneath=lambda: (self.top, rel))

    def read(self, rel: str) -> dict:
        try:
            tree, base = self.adapter(rel).read()
        except (OSError, UnicodeDecodeError):
            raise Fault("not_found", f"no document {rel}") from None
        return {"tree": {"text": tree.text}, "base": base}

    def write(self, body: dict) -> dict:
        rel = clean_document(body.get("document"))
        author, note, base, tree = body.get("author"), body.get("note", ""), body.get("base"), body.get("tree")
        who = self.authors.get(author) if isinstance(author, str) else None
        if who is None:
            raise Fault("unknown_author", "this service has no author for the member who wrote")
        text = tree.get("text") if isinstance(tree, dict) else None
        if not isinstance(text, str) or not isinstance(base, str) or not isinstance(note, str) or "\0" in note:
            raise Fault("bad_request", "write needs tree.text, base and a note, all text")
        if not text.strip():
            return rda.refused("a document is not written empty")      # the one rule of this service: a source's own are its owner's
        try:
            out = self.adapter(rel).write(rda.Tree(text), base, author=author, note=note)
        except (OSError, UnicodeDecodeError):
            raise Fault("not_found", f"no document {rel}") from None
        if out["outcome"] == "written":
            self.commit(rel, who, note)
        return out

    # ── git ─────────────────────────────────────────────────────────────────
    def _git(self, *args, env=None):
        return subprocess.run(["git", "-C", str(self.top), *args], capture_output=True, text=True, timeout=30,
                              env={**os.environ, **(env or {})})

    def _inside_git(self) -> bool:
        try:
            return self._git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
        except (OSError, subprocess.SubprocessError):
            return False

    def commit(self, rel: str, who: tuple, note: str) -> None:
        """The change to `rel`, committed as the mapped author. A failure is said on stderr and never fails the write: the text is
        on disk and the base the hub is given is of it."""
        if not self.git:
            return
        name, email = who
        env = {"GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email}
        try:
            self._git("add", "--", rel)
            got = self._git("-c", "core.hooksPath=/dev/null", "commit", "--no-verify", "--quiet", "--only",
                            f"--author={name} <{email}>", "-m", note.strip() or f"Edit {rel}", "--", rel, env=env)
            if got.returncode not in (0, 1):                 # 1: nothing to commit, the text was the same
                print(f"source service: git commit of {rel} failed ({got.returncode})", file=sys.stderr, flush=True)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"source service: git commit of {rel} failed ({type(e).__name__})", file=sys.stderr, flush=True)


def make_handler(service: Service):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status: int, payload: dict):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, code: str, message: str):
            self._send(status_of(code), {"error": {"code": code, "message": message}})

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not service.authorised(self.headers.get("Authorization")):
                # the body is left unread and the connection closed: nothing is done for a caller without the bearer
                self.close_connection = True
                return self._error("unauthorized", "a request carries the hub's bearer")
            if not 0 <= length <= BODY_MAX:
                self.close_connection = True
                return self._error("bad_request", "the body is missing or too large")
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if not isinstance(body, dict):
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return self._error("bad_request", "the body is not a JSON object")
            try:
                self._send(200, service.handle(self.path.strip("/"), body))
            except Fault as f:
                self._error(f.code, f.message)
            except Exception:           # nothing of the exception leaves: it could name a path
                print("source service: a request failed", file=sys.stderr, flush=True)
                self._error("unavailable", "the service could not do that")

        def do_GET(self):
            self._error("bad_request", "every call is a POST")
    return Handler


class _UnixServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class _TcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(service: Service, *, socket_path: str | None = None, port: int | None = None, ready=None):
    handler = make_handler(service)
    if socket_path:
        p = Path(socket_path)
        if p.is_socket():
            p.unlink()
        old = os.umask(0o177)
        try:
            server = _UnixServer(str(p), handler)
        finally:
            os.umask(old)
    else:
        server = _TcpServer(("127.0.0.1", port), handler)
    if ready is not None:
        ready(server)
    server.serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m sheafmd.sourceservice", description=__doc__.split("\n\n")[0])
    ap.add_argument("--folder", required=True)
    ap.add_argument("--secrets", required=True, help="the file that holds the hub's bearer")
    ap.add_argument("--authors", required=True, help="the table of members and their commit authors")
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--socket")
    where.add_argument("--port", type=int)
    a = ap.parse_args(argv)
    if not Path(a.folder).is_dir():
        raise SystemExit(f"{a.folder}: is not a folder")
    service = Service(a.folder, read_bearer(a.secrets), read_authors(a.authors))
    serve(service, socket_path=a.socket, port=a.port,
          ready=lambda s: print("listening", flush=True))


if __name__ == "__main__":
    main()
