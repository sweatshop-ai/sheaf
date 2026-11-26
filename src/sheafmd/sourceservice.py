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

What it assumes, and enforces where it can: the service owns its folder and its repository. It is a single writer: no concurrent
local edits and no Git operation running beside it, and the root is not replaced while it runs. It is a reference implementation
and the contract suite's partner, not hardened for a shared working copy. The root is opened once at start and every path is opened
from that descriptor, never following a link; one lock covers a write from the look at the file to the end of the commit; the
service refuses to start, and refuses each write with `unavailable`, while a merge, rebase, cherry-pick or revert is in progress
or the index holds staged changes.
"""
import argparse
import base64
import binascii
import hmac
import json
import os
import re
import secrets
import socket
import socketserver
import stat
import subprocess
import sys
import threading
import time
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
        self._root = os.open(self.top, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)    # held for the life of the service
        self._bearer = bearer.encode("utf-8")
        self.authors = authors
        self.git = self._inside_git()
        self._writing = threading.Lock()      # one write at a time, from the file's check to the end of its commit
        self._broken = False                  # set when a failed write could not be cleaned up: the service takes no write until restarted
        busy = self._busy() if self.git else None
        if busy:
            self.close()
            raise SystemExit(f"{self.top}: {busy}; the service does not start until the repository is quiet")

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
        fd = os.dup(self._root)
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

    def close(self) -> None:
        fd, self._root = getattr(self, "_root", -1), -1
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass

    def __del__(self):
        self.close()

    def read(self, rel: str) -> dict:
        with self._writing:            # a write in progress is not shown: its text is tentative until git has taken it
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
        with self._writing:       # the file and the commit are one step: a second write cannot come between them
            if self._broken:
                raise Fault("unavailable", "an earlier write could not be cleaned up: the service takes no write until it is restarted")
            busy = self._busy() if self.git else None
            if busy:
                raise Fault("unavailable", f"{busy}: the folder takes no write until it is over")
            before, mode = self._bytes_of(rel)
            try:
                old = before.decode("utf-8")
            except UnicodeDecodeError:
                raise Fault("not_found", f"no document {rel}") from None
            if rds.md_hash(old) != base:
                return rda.conflict(rds.md_hash(old))
            if text == old:
                return rda.written(base)               # the text the member was shown is the text now: nothing to commit
            done, clean = False, True
            try:
                try:
                    self._put(rel, text.encode("utf-8"), mode)
                except (OSError, Fault):
                    return rda.refused("the document could not be written: it is as it was")
                done = self.commit(rel, who, note)
            finally:
                if not done:
                    clean = self._undo(rel, before, mode)
            if not clean:
                raise Fault("unavailable", "the write failed and could not be cleaned up: the service takes no write until it is restarted")
            if not done:
                return rda.refused("the change could not be recorded in the folder's history: the document is as it was")
        return rda.written(rds.md_hash(text))

    def _put(self, rel: str, data: bytes, mode: int) -> None:
        """The file `rel` replaced by `data` whole: a sibling made with O_EXCL through the folder's descriptor, written and
        synced from its own descriptor, then renamed over the file. A failed sync of the folder after the rename is not a failure:
        the file is replaced."""
        fd, parent, name = self._open(rel, os.O_RDONLY)
        os.close(fd)
        tmp = None
        try:
            for _ in range(8):             # a short name of its own, whatever the document's: a long one must still be writable
                name_tmp = f".sheaf-{secrets.token_hex(4)}"
                try:
                    out = os.open(name_tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
                except FileExistsError:
                    continue
                tmp = name_tmp
                break
            else:
                raise OSError("no free temporary name")
            with os.fdopen(out, "wb") as f:
                f.write(data)
                f.flush()
                os.fchmod(f.fileno(), mode)
                os.fsync(f.fileno())
            os.rename(tmp, name, src_dir_fd=parent, dst_dir_fd=parent)
            tmp = None
            try:
                os.fsync(parent)
            except OSError:
                pass
        finally:
            try:
                if tmp is not None:
                    os.unlink(tmp, dir_fd=parent)
            except OSError:
                pass
            finally:
                os.close(parent)

    def _undo(self, rel: str, before: bytes, mode: int) -> bool:
        """What a failed write leaves put back: nothing staged for `rel`, and its previous bytes, each step on its own so that one
        failing does not skip the other. False when a step failed: the service is then unavailable until it is restarted."""
        clean = True
        try:
            if self.git:
                got = self._git("reset", "-q", "--", rel)
                if got.returncode != 0:
                    raise OSError(f"reset exited {got.returncode}")
        except (OSError, subprocess.SubprocessError) as e:
            clean = False
            print(f"source service: the index entry of {rel} could not be reset ({type(e).__name__})", file=sys.stderr, flush=True)
        finally:
            try:
                self._put(rel, before, mode)
            except (OSError, Fault):
                clean = False
                print(f"source service: {rel} could not be put back after a failed commit", file=sys.stderr, flush=True)
        if not clean:
            self._broken = True
        return clean

    # ── git ─────────────────────────────────────────────────────────────────
    def _git(self, *args, env=None):
        return subprocess.run(["git", "-C", str(self.top), *args], capture_output=True, text=True, timeout=30,
                              env={**os.environ, **(env or {}), "GIT_LITERAL_PATHSPECS": "1"})   # a name is a file, never a glob or a magic pathspec

    def _inside_git(self) -> bool:
        try:
            return self._git("rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
        except (OSError, subprocess.SubprocessError):
            return False

    def _busy(self) -> str | None:
        """Why the repository takes no write now, or None: a merge, rebase, cherry-pick or revert in progress, or staged changes
        that a commit of one file must not be mixed with. Where git cannot say, it is busy."""
        try:
            gdir = self._git("rev-parse", "--absolute-git-dir")
            if gdir.returncode != 0:
                return "the repository cannot be read"
            for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
                if os.path.lexists(os.path.join(gdir.stdout.strip(), marker)):
                    return "a merge, rebase, cherry-pick or revert is in progress"
            # the whole repository, whatever `diff.relative` says
            if self._git("-c", "diff.relative=false", "diff", "--cached", "--quiet", "--no-relative").returncode != 0:
                return "the index holds staged changes"
        except (OSError, subprocess.SubprocessError):
            return "the repository cannot be read"
        return None

    def commit(self, rel: str, who: tuple, note: str) -> bool:
        """The change to `rel`, committed as the mapped author, with git's own filters and ignore rules: True when it is in the
        history (or there is no history, or nothing differed), False when a git step failed (said on stderr; the caller puts the
        file back)."""
        if not self.git:
            return True
        name, email = who
        env = {"GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email}
        head = self._git("rev-parse", "-q", "--verify", "HEAD").stdout.strip()
        try:
            added = self._git("add", "--", rel)
            if added.returncode != 0:
                print(f"source service: git add of {rel} failed ({added.returncode})", file=sys.stderr, flush=True)
                return False
            got = self._git("-c", "core.hooksPath=/dev/null", "commit", "--no-verify", "--quiet", "--only",
                            f"--author={name} <{email}>", "-m", note.strip() or f"Edit {rel}", "--", rel, env=env)
            if got.returncode == 0:
                return True
            if got.returncode == 1 and self._git("diff", "--cached", "--quiet", "--", rel).returncode == 0:
                return True                     # 1 with nothing staged: the text was the same
            print(f"source service: git commit of {rel} failed ({got.returncode})", file=sys.stderr, flush=True)
        except subprocess.TimeoutExpired:
            if self._landed(rel, head):
                return True                      # the commit went in before the time ran out
            print(f"source service: git commit of {rel} timed out", file=sys.stderr, flush=True)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"source service: git commit of {rel} failed ({type(e).__name__})", file=sys.stderr, flush=True)
        return False

    def _landed(self, rel: str, head: str) -> bool:
        """After a git timeout: HEAD moved, and what it holds for `rel` is the file as written."""
        try:
            now = self._git("rev-parse", "-q", "--verify", "HEAD").stdout.strip()
            if not now or now == head:
                return False
            listed = self._git("ls-tree", "HEAD", "--", rel).stdout.split()
            mine = self._git("hash-object", "--", rel).stdout.strip()
            return len(listed) >= 3 and listed[2] == mine
        except (OSError, subprocess.SubprocessError):
            return False


def make_handler(service: Service):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status: int, payload: dict, close: bool = False):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            if close:
                self.send_header("Connection", "close")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, code: str, message: str, close: bool = False):
            self._send(status_of(code), {"error": {"code": code, "message": message}}, close)

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not service.authorised(self.headers.get("Authorization")):
                # nothing is done for a caller without the bearer, and its body is not read for the answer: it is told with
                # `Connection: close`, our side is shut for writing so the answer is delivered whole, and what the caller still
                # sends is drained for a moment, up to a small size, so that closing does not reset the connection
                self.close_connection = True
                self._error("unauthorized", "a request carries the hub's bearer", close=True)
                try:
                    self.connection.shutdown(socket.SHUT_WR)
                    until, left = time.monotonic() + 2.0, 65536       # one overall deadline, then it is closed
                    while left > 0 and (room := until - time.monotonic()) > 0:
                        self.connection.settimeout(room)
                        if not (chunk := self.connection.recv(min(left, 8192))):
                            break
                        left -= len(chunk)
                except OSError:
                    pass
                return
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
