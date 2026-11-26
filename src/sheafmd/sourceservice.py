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
import tempfile
import threading
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


class GitFailed(Exception):
    """A git step that ended with an error."""


class Conflicted(Exception):
    """The file is no longer the text that was judged."""


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
        self._writing = threading.Lock()      # one write at a time, from the file's check to the end of its commit

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
    def _open(self, rel: str, flags: int, mode: int = 0o600):
        """`(descriptor, parent descriptor, name)` of the file `rel`: every folder and the file are opened from the one above by
        `openat`, with no link followed at any step (`O_NOFOLLOW`), so a link put there at any moment is a refusal, never a way
        out of the folder. The parent descriptor is the caller's to close. `not_found` for what is not a plain file of the folder."""
        gone = Fault("not_found", f"no document {rel}")
        *folders, name = rel.split("/")
        fd = os.open(self.top, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in folders:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = nxt
            return os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, mode, dir_fd=fd), fd, name
        except OSError:
            os.close(fd)
            raise gone from None
        except BaseException:
            os.close(fd)
            raise

    def _bytes_of(self, rel: str) -> tuple[bytes, int]:
        """The bytes of the file `rel` and its mode: a regular file with one name, reached through no link."""
        fd, parent, _ = self._open(rel, os.O_RDONLY)
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
                raise Fault("not_found", f"no document {rel}")
            with os.fdopen(fd, "rb", closefd=False) as f:
                return f.read(), stat.S_IMODE(st.st_mode)
        finally:
            os.close(fd)
            os.close(parent)

    def _text_of(self, rel: str) -> tuple[str, int]:
        data, mode = self._bytes_of(rel)
        try:
            return data.decode("utf-8"), mode
        except UnicodeDecodeError:
            raise Fault("not_found", f"no document {rel}") from None

    def read(self, rel: str) -> dict:
        text, _ = self._text_of(rel)
        return {"tree": {"text": text}, "base": rds.md_hash(text)}

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
        with self._writing:       # one write at a time, from the look at the file to the end of the replace
            old, mode = self._text_of(rel)
            if rds.md_hash(old) != base:
                return rda.conflict(rds.md_hash(old))
            if text == old:
                return rda.written(base)                     # the text the member was shown is the text now: nothing to commit or replace
            sent = None
            try:
                sent = self._commit(rel, text, mode, who, note)            # first, off the real index: a failure leaves nothing to undo
            except (OSError, subprocess.SubprocessError, GitFailed) as e:
                print(f"source service: the history of {rel} could not be written ({type(e).__name__})", file=sys.stderr, flush=True)
                return rda.refused("the change could not be recorded in the folder's history: the document is as it was")
            try:
                self._replace(rel, old, text, mode)                        # last: only while the file is still the text that was judged
            except Conflicted:
                self._take_back(sent)
                return rda.conflict(rds.md_hash(self._text_of(rel)[0]))
            except (OSError, Fault):
                self._take_back(sent)
                return rda.refused("the document could not be written: it is as it was")
            self._follow(sent, rel)
        return rda.written(rds.md_hash(text))

    def _replace(self, rel: str, old: str, new: str, mode: int) -> None:
        """The file `rel` replaced by `new` whole: a sibling made beside it, then renamed over it, only while the file still holds
        `old`. Nothing is followed: the folder is held by its descriptor from the first look to the rename."""
        fd, parent, name = self._open(rel, os.O_RDONLY)
        os.close(fd)
        tmp = f".{name}.sheaf-tmp"
        try:
            try:
                os.unlink(tmp, dir_fd=parent)
            except FileNotFoundError:
                pass
            out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            with os.fdopen(out, "wb") as f:
                f.write(new.encode("utf-8"))
                f.flush()
                os.fchmod(f.fileno(), mode)
                os.fsync(f.fileno())
            if self._bytes_of(rel)[0] != old.encode("utf-8"):
                raise Conflicted
            os.rename(tmp, name, src_dir_fd=parent, dst_dir_fd=parent)
            tmp = None
            os.fsync(parent)
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp, dir_fd=parent)
                except OSError:
                    pass
            os.close(parent)

    # ── git ─────────────────────────────────────────────────────────────────
    def _git(self, *args, env=None, data: bytes | None = None):
        return subprocess.run(["git", "-C", str(self.top), *args], capture_output=True, input=data, timeout=30,
                              env={**os.environ, **(env or {}), "GIT_LITERAL_PATHSPECS": "1"})   # a name is a file, never a glob or a magic pathspec

    def _out(self, *args, env=None, data: bytes | None = None) -> str:
        got = self._git(*args, env=env, data=data)
        if got.returncode != 0:
            raise GitFailed(args[0])
        return got.stdout.decode("utf-8", "replace").strip()

    def _inside_git(self) -> bool:
        try:
            return self._out("rev-parse", "--is-inside-work-tree") == "true"
        except (OSError, subprocess.SubprocessError, GitFailed):
            return False

    def _commit(self, rel: str, text: str, mode: int, who: tuple, note: str):
        """The commit of `text` as the file `rel`, made without the work tree or the real index: the blob is written, a tree is built
        in a temporary index seeded from HEAD, the commit is made with the mapped author, and HEAD moves to it only if it is still
        where it was (compare and swap). `(new, old)` ids, or None where there is no history. A failure at any step has changed
        no file, no index and no reference."""
        if not self.git:
            return None
        name, email = who
        env = {"GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email}
        old = self._git("rev-parse", "-q", "--verify", "HEAD^{commit}")
        old_id = old.stdout.decode().strip() if old.returncode == 0 else None
        path = self._out("rev-parse", "--show-prefix") + rel          # the name in the repository, which may hold more than the folder
        blob = self._out("hash-object", "-w", "--no-filters", "--stdin", data=text.encode("utf-8"))
        with tempfile.TemporaryDirectory(prefix="sheaf-idx-") as scratch:
            idx = {"GIT_INDEX_FILE": os.path.join(scratch, "index")}
            if old_id:
                self._out("read-tree", old_id, env=idx)
            kind = "100755" if mode & 0o111 else "100644"
            self._out("update-index", "--add", "--cacheinfo", f"{kind},{blob},{path}", env=idx)
            tree = self._out("write-tree", env=idx)
        cmd = ["commit-tree", tree, "-m", note.strip() or f"Edit {rel}"]
        if old_id:
            cmd[2:2] = ["-p", old_id]
        if self._git("config", "--type=bool", "commit.gpgsign").stdout.strip() == b"true":
            cmd.append("-S")                                             # commit-tree does not read the setting itself
        new = self._out(*cmd, env=env)
        self._out("update-ref", "-m", f"commit: {note.strip().splitlines()[0] if note.strip() else 'edit ' + rel}",
                  "HEAD", new, old_id or "0" * len(new))
        return new, old_id

    def _take_back(self, sent) -> None:
        """HEAD put back where it was, only if it is still at the commit just made: for a write whose last step failed."""
        if sent is None:
            return
        new, old = sent
        try:
            if old:
                self._out("update-ref", "-m", "sheaf: take back", "HEAD", old, new)
            else:
                self._out("update-ref", "-m", "sheaf: take back", "-d", "HEAD", new)
        except (OSError, subprocess.SubprocessError, GitFailed):
            print("source service: the commit of a failed write could not be taken back", file=sys.stderr, flush=True)

    def _follow(self, sent, rel: str) -> None:
        """After the commit and the file agree: the real index entry of `rel` moves to the new text only where it held what HEAD
        held before, so a staged edit of someone is never replaced. A failure here changes nothing that was written."""
        if sent is None:
            return
        new, old = sent
        try:
            path = self._out("rev-parse", "--show-prefix") + rel
            tracked = self._out("ls-tree", old, "--", path).split() if old else []
            staged = self._out("ls-files", "-s", "--", path).split()
            was = (tracked[0], tracked[2]) if tracked else None
            now = (staged[0], staged[1]) if staged else None
            if was == now:                       # the index holds what HEAD held: it follows HEAD; any other text in it is someone's
                blob = self._out("rev-parse", f"{new}:{path}")
                self._out("update-index", "--add", "--cacheinfo", f"{(was or ('100644',))[0]},{blob},{path}")
        except (OSError, subprocess.SubprocessError, GitFailed):
            print(f"source service: the index entry of {rel} could not be brought up to date", file=sys.stderr, flush=True)


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
                # nothing is done for a caller without the bearer: a small body is read and dropped (a close with it unread resets the
                # connection and the caller never sees the answer), a large one is left, and the connection is closed
                if 0 < length <= 65536:
                    self.rfile.read(length)
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
