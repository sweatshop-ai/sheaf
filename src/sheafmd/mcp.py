"""
sheafmd.mcp — the MCP door: JSON-RPC 2.0 and its tools (SPEC 12).

`Door(hub).handle(raw, caller)` takes the body of one `POST /_/mcp` and returns the HTTP status
and the JSON-RPC answer (None for a message that has none: a notification, or a reply to
nothing). The handler (hub/handler.py) authenticates the caller; the stdio transport (`sheaf
mcp`, `Stdio` below) forwards each line to that route, so there is one implementation of the
protocol and it runs in the hub, next to the Live Documents.

`display_for` and `Stdio` are the other end, what `sheaf mcp` runs: it reads one message per line
on stdin, posts it through a `DoorLink` and writes each answer as one line on stdout. Nothing but
protocol goes to stdout; whatever it has to say goes to stderr.

Not the MCP SDK: the door is small enough to read in one sitting, and runs inside the hub's own
server (SPEC 3.2).
"""
import errno
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, paths
from . import comments as rdc
from .agents import detect
from .hub.auth import clean_display
from .hub.client import HubUnavailable
from .hub.roots import Address, NotFound, address_of_url, in_git_dir
from .hub import visibility
from .hub.state import TokenRow
from .render import COMMENT_RE as HTML_COMMENT_RE, strip_comments
from .source import check_create, create_file, md_hash, now, update_file

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "sheaf keeps comment threads inside markdown files. Use `threads` to read what was asked on "
    "a document, `reply` to answer (role `action` after you acted on a Tell, `answer` when you "
    "only answer), and `resolve` when a thread is done. A Tell from sheaf names the document and "
    "the comment id. Where you may work on pages, `read` gives a document's text and its hash, "
    "`create` makes a new page and `update` replaces the text of one, given the hash you read it "
    "with; keep every comment in the text you send.")

WALK_LIMIT = 2000                # files of a root that is not a git work tree (SPEC 8.6, D15)
DOT_ORDER = {"red": 0, "orange": 1, "blue": 2, "green": 3}

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
INTERNAL_ERROR = -32603

_DOC = {"type": "string", "description": "The document: `<root>/<path>` as the hub names it, "
        "the URL of its page, or the absolute path of the .md file."}
_ID = {"type": "string", "description": "The comment's id, such as `c3`."}
_TEXT = {"type": "string", "description": "The whole text of the page, markdown, at most 1 MiB."}
TOOLS = {
    "documents": {
        "description": "List the documents that have open comments, to find what waits for you. "
                       "Each row: doc, url, path, open (open comments), unread (threads with a "
                       "message the person has not seen) and dot (red, orange, blue or green). A root "
                       "whose folder the hub cannot enter comes last, as a row of its own: root and "
                       "closed (why, such as Permission denied).",
        "annotations": {"readOnlyHint": True},
        "properties": {
            "root": {"type": "string", "description": "Only the documents of this root."},
            "open_only": {"type": "boolean", "description": "Only documents with open comments "
                                                            "(the default); false lists every one."}},
        "required": []},
    "threads": {
        "description": "Read the comment threads of a document: who asked what, on which "
                       "passage, and the replies so far.",
        "annotations": {"readOnlyHint": True},
        "properties": {
            "doc": _DOC,
            "status": {"type": "string", "enum": ["open", "resolved", "all"],
                       "description": "Which threads (default open)."}},
        "required": ["doc"]},
    "reply": {
        "description": "Reply in a comment thread. Use role `action` after you did what a Tell "
                       "asked, `answer` when you only answer in words.",
        "properties": {
            "doc": _DOC, "id": _ID,
            "text": {"type": "string", "description": "What you did, or your answer."},
            "role": {"type": "string", "enum": list(rdc.ROLES),
                     "description": "`answer` (the default) or `action`."},
            "resolve": {"type": "boolean", "description": "Also mark the thread resolved."}},
        "required": ["doc", "id", "text"]},
    "resolve": {
        "description": "Mark a comment thread resolved.",
        "properties": {"doc": _DOC, "id": _ID},
        "required": ["doc", "id"]},
    "read": {
        "description": "Read a document's text as the file holds it now, with its hash. Send the "
                       "text back to `update`, comments and all, with that hash. With comments "
                       "false the text comes without its comments, to use it (as a mail, say), "
                       "not to send it back.",
        "annotations": {"readOnlyHint": True},
        "properties": {
            "doc": _DOC,
            "comments": {"type": "boolean", "description": "Keep the comments in the text (the "
                                                          "default); false strips every HTML "
                                                          "comment, threads and any other."}},
        "required": ["doc"]},
    "create": {
        "description": "Make a new page: a .md file that does not exist yet, in a folder that "
                       "does, inside a root the hub already has. It never replaces a file. The "
                       "text holds no comment.",
        "properties": {
            "doc": {"type": "string", "description": "The new document: `<root>/<path>` ending in "
                                                     ".md, or the absolute path of the file to make."},
            "text": _TEXT},
        "required": ["doc", "text"]},
    "update": {
        "description": "Replace the whole text of a page, against the hash you read it with: if "
                       "the file changed since, nothing is written and you read it again. The "
                       "text must keep every comment of the file exactly as `read` gave it.",
        "properties": {
            "doc": _DOC, "text": _TEXT,
            "expected_hash": {"type": "string", "description": "The hash `read` or `create` "
                                                               "gave for the text you changed."}},
        "required": ["doc", "text", "expected_hash"]},
}
PAGE_TOOLS = ("read", "create", "update")    # the key, or a token made with --write (SPEC 9.7)
WRITE_TOOLS = ("create", "update")           # each call leaves a row in the diagnostics log (SPEC 15)
MAX_TEXT = 1024 * 1024           # bytes of UTF-8 a create or an update may write (SPEC 12)
NO_RIGHT = ("This token reads and answers comments; it does not read, make or change pages. A "
            "token that does is made with `sheaf token add NAME --write`.")
NOT_IN_A_ROOT = "is not inside a root of this hub; a page is made only in a root the hub already has."
HASH_RE = re.compile(r"[0-9a-f]{16}")


@dataclass(frozen=True)
class Caller:
    """Who is at the door. `display` signs the replies. `token` is the MCP token an HTTP client
    proved itself with, confined to the roots the hub already has (SPEC 9.7), and whether it was
    made to work on pages; None is the key (the stdio door, which runs as the user)."""
    display: str
    token: TokenRow | None = None

    @property
    def token_name(self) -> str | None:
        return self.token.name if self.token else None

    @property
    def may_add_roots(self) -> bool:
        return self.token is None

    @property
    def may_write(self) -> bool:
        return self.token is None or self.token.write


class ToolError(Exception):
    """A tool that cannot do what it was asked: one sentence, handed back as the result. `why` is
    all the diagnostics log keeps of a refused `create` or `update`, a few fixed words: the
    sentence may quote the document (a comment's id is the text's own), and the log never holds
    the text (SPEC 15)."""

    def __init__(self, sentence: str, why: str = "refused"):
        super().__init__(sentence)
        self.why = why


class Stale(ToolError):
    """An update against a text the file no longer holds."""

    def __init__(self, sentence: str):
        super().__init__(sentence, "stale")


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _is_id(v) -> bool:
    return isinstance(v, str) or (isinstance(v, int) and not isinstance(v, bool))


def _schema(name: str) -> dict:
    t = TOOLS[name]
    out = {"type": "object", "properties": t["properties"], "additionalProperties": False}
    if t["required"]:
        out["required"] = list(t["required"])
    return out


def _check(name: str, args: dict) -> dict:
    """The arguments of a call, checked against the tool's own schema; a ToolError says which."""
    t = TOOLS[name]
    for k in args:
        if k not in t["properties"]:
            raise ToolError(f"{name} has no argument {k}.")
    for k in t["required"]:
        if k not in args:
            raise ToolError(f"{k} is required.")
    for k, v in args.items():
        spec = t["properties"][k]
        if spec["type"] == "string" and not isinstance(v, str):
            raise ToolError(f"{k} must be text.")
        if spec["type"] == "boolean" and not isinstance(v, bool):
            raise ToolError(f"{k} must be true or false.")
        if "enum" in spec and v not in spec["enum"]:
            raise ToolError(f"{k} must be one of {', '.join(spec['enum'])}.")
    return args


def markdown_files(root) -> list[str]:
    """The `.md` files of a root as paths inside it, by the rules of SPEC 8.6: in a git work
    tree the files git lists (tracked and untracked, not ignored); elsewhere a walk that skips
    `.git`, `node_modules` and every folder starting with a dot, and stops at WALK_LIMIT."""
    if root.git:
        try:
            r = subprocess.run(["git", "-C", str(root.path), "ls-files", "-z", "-co",
                                "--exclude-standard", "--", "*.md", ":!:**/node_modules/**"],
                               capture_output=True, timeout=10)
            if r.returncode == 0:
                # the pathspec above needs a folder over node_modules; a top-level one is dropped here
                found = (os.fsdecode(p) for p in r.stdout.split(b"\0") if p)
                return sorted(p for p in found if "node_modules" not in p.split("/"))
        except (OSError, subprocess.SubprocessError):
            pass                              # not a work tree any more: walk it like a folder
    out = []
    for folder, dirs, files in os.walk(root.path):
        dirs[:] = sorted(d for d in dirs if d != "node_modules" and not d.startswith("."))
        for f in sorted(files):
            if f.endswith(".md"):
                out.append((Path(folder) / f).relative_to(root.path).as_posix())
                if len(out) >= WALK_LIMIT:
                    return out
    return out


class Door:
    def __init__(self, hub):
        self.hub = hub
        # real path -> ((inode, mtime_ns, ctime_ns, size), [(id, messages, last author)] of its open threads,
        # its front matter): a file is read again only when it changed, a write that kept its size and put
        # its time back included (SPEC 8.6, 9.11)
        self._open_threads: dict = {}
        self._tools = {"documents": self._documents, "threads": self._threads,
                       "reply": self._reply, "resolve": self._resolve, "read": self._read,
                       "create": self._create, "update": self._update}

    # ── JSON-RPC ─────────────────────────────────────────────────────────────
    def handle(self, raw: bytes, caller: Caller) -> tuple[int, dict | None]:
        """(HTTP status, answer). The answer is None when there is nothing to say (202)."""
        try:
            message = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return 400, _error(None, PARSE_ERROR, "The body is not JSON.")
        if isinstance(message, list):
            return 400, _error(None, INVALID_REQUEST, "Batches are not supported: send one message.")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return 400, _error(None, INVALID_REQUEST, "That is not a JSON-RPC 2.0 message.")
        if "method" not in message:
            if "result" in message or "error" in message:
                return 202, None            # an answer to something the client thinks we asked
            return 400, _error(None, INVALID_REQUEST, "The message has no method.")
        method, params = message["method"], message.get("params")
        if (not isinstance(method, str) or ("id" in message and not _is_id(message["id"]))
                or (params is not None and not isinstance(params, (dict, list)))):
            return 400, _error(None, INVALID_REQUEST, "That is not a valid JSON-RPC request.")
        if "id" not in message:
            return 202, None                # a notification: initialized, cancelled, anything
        return 200, self._request(message["id"], method, params, caller)

    def _request(self, id_, method: str, params, caller: Caller) -> dict:
        if method == "initialize":
            asked = params.get("protocolVersion") if isinstance(params, dict) else None
            version = asked if isinstance(asked, str) and asked in PROTOCOLS else PROTOCOLS[0]
            return self._ok(id_, {"protocolVersion": version, "capabilities": {"tools": {}},
                                  "serverInfo": {"name": "sheaf", "version": __version__},
                                  "instructions": INSTRUCTIONS})
        if method == "ping":
            return self._ok(id_, {})
        if method == "tools/list":
            return self._ok(id_, {"tools": [
                {"name": n, "description": t["description"], "inputSchema": _schema(n),
                 **({"annotations": t["annotations"]} if "annotations" in t else {})}
                for n, t in TOOLS.items() if caller.may_write or n not in PAGE_TOOLS]})
        if method == "tools/call":
            return self._call(id_, params, caller)
        return _error(id_, METHOD_NOT_FOUND, f"There is no method {method}.")

    @staticmethod
    def _ok(id_, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": id_, "result": result}

    def _call(self, id_, params, caller: Caller) -> dict:
        name = params.get("name") if isinstance(params, dict) else None
        if not isinstance(name, str) or name not in self._tools:
            return _error(id_, INVALID_PARAMS, f"That is not one of the door's tools ({', '.join(self._tools)}).")
        args = params.get("arguments")
        args = {} if args is None else args
        if not isinstance(args, dict):
            return _error(id_, INVALID_PARAMS, "The arguments are not an object.")
        try:
            out = self._logged(name, args, caller) if name in WRITE_TOOLS else self._run(name, args, caller)
            return self._ok(id_, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                                  "isError": False})
        except ToolError as e:
            return self._ok(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception:
            doc = args.get("doc") if isinstance(args.get("doc"), str) else None
            self.hub.record_exception("mcp-failed", doc, tool=name)
            return self._ok(id_, {"content": [{"type": "text", "text":
                                               "The hub failed on this call; the details are in `sheaf diag`."}],
                                  "isError": True})

    # ── naming a document ────────────────────────────────────────────────────
    def _address(self, doc: str, caller: Caller) -> str:
        """`<root>/<path>` of the document `doc` names: that address itself, the URL of its page,
        or the absolute path of the .md. A caller who may add roots (the key) has the root of a
        path registered; a token (9.7) is held to the roots the hub already has."""
        doc = _named(doc)
        if "://" in doc:
            address = self._address_of_url(doc)
        elif os.path.isabs(doc):
            address = self._address_of_path(doc, caller)
        else:
            address = doc
        try:
            path = self.hub.roots.document(address)
        except NotFound:
            raise _absent(doc) from None
        if self._judged(caller):
            # Before any other check of the call, so no answer tells a sheaf the caller may not see from none;
            # each tool judges again on the text it reads.
            try:
                self._seen(path.read_text(encoding="utf-8"), address, caller, doc)
            except (OSError, UnicodeDecodeError):
                raise _absent(doc) from None        # as a member is answered for a file it cannot read
        return address

    def _judged(self, caller: Caller) -> bool:
        """Whether visibility (9.11) holds `caller`: a token, in proxy mode."""
        return caller.token is not None and getattr(self.hub, "proxy", None) is not None

    def _member(self, caller: Caller):
        """The member `caller` acts for (9.11): in proxy mode, the one whose `tokens` name its token; None for
        the key, a token bound to nobody, and every caller in loopback mode."""
        return self.hub.proxy.member_of_token(caller.token.name) if self._judged(caller) else None

    def _sees(self, fm: dict, address: str, caller: Caller, owns: bool | None = None) -> bool:
        """Whether `caller` may see the sheaf at `address` whose front matter is `fm` (9.11). In proxy mode a
        token acts for the member whose `tokens` name it and sees what that member sees, in that member's
        roots only; a token bound to nobody sees every root (9.7) and no sheaf that is its owner's alone. The
        key is the hub's own account, which reads every file. `owns`, when given, is `member_owns` for the
        token's member, already asked."""
        if not self._judged(caller):
            return True
        member = self._member(caller)
        if owns is None and member is not None:
            owns = self.hub.member_owns(member, address)
        if member is not None and not owns:
            return False
        if visibility.effective(fm) == "project":
            return True
        return member is not None and visibility.visible_to(fm, member, self.hub.assignees(address, fm))

    def _seen(self, text: str, address: str, caller: Caller, doc: str) -> str:
        """`text`, the text of the document at `address`, when `caller` may see it; else the answer to a
        `doc` that names no document."""
        if not self._sees(visibility.front_matter(text), address, caller):
            raise _absent(doc)
        return text

    @staticmethod
    def _address_of_url(url: str) -> str:
        try:
            u = urlsplit(url)
            host = u.hostname
        except ValueError:
            host = None
        address = address_of_url(u.path) if host else None
        if u.scheme != "http" or host not in ("127.0.0.1", "localhost") or address is None:
            raise ToolError("That is not the URL of a page on a sheaf hub of this machine.")
        return address

    def _address_of_path(self, path: str, caller: Caller) -> str:
        roots, md = self.hub.roots, Path(path)
        try:
            if caller.may_add_roots:
                if not path.endswith(".md") or not paths.is_file(md):
                    raise ToolError(f"{path} is not an existing .md file.")
                return roots.address(md)
            root = roots.lookup(md)
            if root is None or ((member := self._member(caller)) is not None and not self.hub.owns(member, root)):
                # a root of another member's is no root to a token bound to one (9.11)
                raise ToolError("A token cannot add a root, and the hub has no root that holds that file.")
            return str(Address(root.name, Path(os.path.realpath(md)).relative_to(root.path).as_posix()))
        except (OSError, ValueError) as e:
            # The key's caller runs as the hub's account and is told why. A token, held to the roots
            # the hub has (9.7), gets one answer for a path outside them, there or not.
            why = f" ({e.strerror})" if caller.may_add_roots and getattr(e, "strerror", None) else ""
            raise ToolError(f"{path} cannot be used as a document{why}.") from None

    def _comments(self, address: str, caller: Caller, doc: str):
        """The comments of the document as the file is now, not as a page was rendered. `doc` is how the
        caller named it, for the answer to one it may not see."""
        try:
            text = self.hub.roots.document(address).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, NotFound):
            raise ToolError(f"{address} cannot be read.") from None
        return rdc.parse(self._seen(text, address, caller, doc))

    def _comment(self, address: str, cid: str, caller: Caller, doc: str):
        c = self._comments(address, caller, doc).by_id(cid)
        if c is None:
            raise ToolError(f"There is no comment {cid} in {address}.")
        return c

    def _write(self, address: str, caller: Caller, doc: str, op: str, fields: dict, role=None):
        """A change to one comment. Through the document's Live Document when the hub has one,
        so open tabs hear of it at once and a Tell wait sees an action reply; straight into the
        file when the hub holds no page for it. Either way the caller's sight of it (9.11) is judged
        again on the file under its lock, so a sheaf that closed since the check takes nothing."""
        entry = self.hub.entries.get(address)

        def guard(t):
            self._seen(t, address, caller, doc)
        try:
            if entry is not None:
                entry.live.comment(op, fields, None, by=caller.display, role=role, announce=True, guard=guard)
            else:
                update_file(self.hub.roots.document(address),
                            lambda t: rdc.apply_op(guard(t) or t, op, fields, caller.display, now(), role))
        except rdc.AnchorError as e:
            raise ToolError(f"{e}.") from None
        except (OSError, UnicodeDecodeError, NotFound):
            raise ToolError(f"{address} could not be written.") from None
        self.hub.committed(address, by=caller.display, what="comment")

    # ── the tools ────────────────────────────────────────────────────────────
    def _open_in(self, path: Path) -> tuple:
        """(open threads, front matter) of the file at `path`, both from one read."""
        st = path.stat()
        key = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
        cached = self._open_threads.get(path)
        if cached and cached[0] == key:
            return cached[1:]
        text = path.read_text(encoding="utf-8")
        threads = []
        if "comment id=" in text:
            for c in rdc.parse(text).comments:
                if c.status == "open":
                    last = c.display(c.replies[-1]) if c.replies else c.by
                    threads.append((c.id, 1 + len(c.replies), last))
        self._open_threads[path] = (key, threads, visibility.front_matter(text))
        return self._open_threads[path][1:]

    def _dot(self, address: str, unread: int, open_: int, asking: set) -> str:
        """The dot of 8.6, as the index page gives it: `asking` holds the documents an Ask runs on."""
        entry = self.hub.entries.get(address)
        if unread or (entry is not None and entry.live.session_question()):
            return "red"
        if address in asking or self.hub.waiting(address):
            return "orange"
        return "blue" if open_ else "green"

    def _documents(self, args: dict, caller: Caller):
        hub = self.hub
        member = self._member(caller)
        if "root" in args:
            root = hub.roots.get(args["root"])
            if root is None or (member is not None and not hub.owns(member, root)):
                raise ToolError(f"There is no root named {args['root']}.")
            wanted = [root]
        else:
            wanted = [r for r in hub.roots.all() if member is None or hub.owns(member, r)]
        asking = {doc for doc, _ in hub.jobs_asking()}
        rows, shut = [], []
        in_git = {}                             # (root, real folder) -> whether 8.2 keeps its files from the root
        owned = {}                              # (root, real folder) -> whether its files are the member's (9.11)
        for root in wanted:
            # A root the hub cannot look into may hold what waits: said by name and why, never its folder (8.6).
            if (why := root.closed()) is not None:
                shut.append({"root": root.name, "closed": why})
                continue
            if root.missing():
                continue
            for rel in markdown_files(root):
                address = str(Address(root.name, rel))
                try:
                    path = hub.roots.resolve(address)          # never a file outside its root
                    folder = (root.name, path.parent)
                    if folder not in in_git:
                        in_git[folder] = in_git_dir(path, root)
                    if in_git[folder]:
                        continue                               # nor one in a git directory
                    threads, fm = self._open_in(path)
                    mtime = path.stat().st_mtime_ns
                except (NotFound, OSError, UnicodeDecodeError):
                    continue
                # Whether the member owns a file asks git of its folder (8.2), and every file of a folder has the
                # same answer: asked once a folder, not once a file.
                if member is not None and folder not in owned:
                    owned[folder] = hub.member_owns(member, address)
                if not self._sees(fm, address, caller, owned.get(folder)):
                    continue                                   # nor a sheaf the caller may not see (9.11)
                if args.get("open_only", True) and not threads:
                    continue
                seen = hub.seen.get(address)
                unread = sum(1 for cid, n, last in threads if last != hub.person and n > seen.get(cid, 0))
                dot = self._dot(address, unread, len(threads), asking)
                rows.append((DOT_ORDER[dot], -mtime, address,
                             {"doc": address, "url": hub.url(address), "path": str(path),
                              "open": len(threads), "unread": unread, "dot": dot}))
        return [row[3] for row in sorted(rows, key=lambda r: r[:3])] + shut

    def _threads(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller)
        status = args.get("status", "open")
        got = self._comments(address, caller, args["doc"])
        return {"doc": address, "url": self.hub.url(address),
                "comments": [{k: v for k, v in c.as_dict().items() if k != "block"}
                             for c in got.comments if status == "all" or c.status == status],
                "malformed": [{"line": m.line, "reason": m.reason} for m in got.malformed]}

    def _reply(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller)
        cid, text = args["id"], args["text"]
        if not text.strip():
            raise ToolError("text is empty.")
        self._comment(address, cid, caller, args["doc"])
        self._write(address, caller, args["doc"], "reply",
                    {"id": cid, "body": text, "resolve": args.get("resolve", False)},
                    role=args.get("role", "answer"))
        c = self._comment(address, cid, caller, args["doc"])
        return {"id": cid, "status": c.status, "replies": c.as_dict()["replies"]}

    def _resolve(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller)
        cid = args["id"]
        if self._comment(address, cid, caller, args["doc"]).status != "resolved":
            self._write(address, caller, args["doc"], "status", {"id": cid, "status": "resolved"})
        return {"id": cid, "status": "resolved"}

    def _read(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller)
        try:
            text = self.hub.roots.document(address).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, NotFound):
            raise ToolError(f"{address} cannot be read.") from None
        out = self._seen(text, address, caller, args["doc"])
        if not args.get("comments", True):
            out = strip_comments(text)
            if "<!--" in out:
                raise ToolError(f"{address} has a `<!--` that nothing closes, at line "
                                f"{_unclosed_line(text, out)}: the page shows nothing after it, "
                                "so its text without comments is not given.")
        return {"doc": address, "url": self.hub.url(address), "hash": md_hash(text), "text": out}

    # ── create and update: a row in the diagnostics log for every call (SPEC 9.7, 15) ─
    def _run(self, name: str, args: dict, caller: Caller):
        """One tool, for a caller that may use it."""
        if name in PAGE_TOOLS and not caller.may_write:
            raise ToolError(NO_RIGHT, "no write right")
        return self._tools[name](_check(name, args), caller)

    def _logged(self, name: str, args: dict, caller: Caller) -> dict:
        who = {"token": caller.token_name, "by": caller.display}
        doc = args.get("doc") if isinstance(args.get("doc"), str) else None
        try:
            out = self._run(name, args, caller)
        except ToolError as e:
            self.hub.record(f"door-{name}", doc, outcome="stale" if isinstance(e, Stale) else "refused",
                            reason=e.why, **who)
            raise
        self.hub.record(f"door-{name}", out["doc"], outcome="written" if out.get("changed", True)
                        else "unchanged", hash=out["hash"], bytes=len(_as_read(args["text"]).encode("utf-8")),
                        **who)
        return out

    @staticmethod
    def _check_size(text: str):
        if len(text.encode("utf-8")) > MAX_TEXT:
            raise ToolError("text is longer than 1 MiB; a page made or changed through the door is at "
                            "most that.", "size")

    def _hidden_root(self, root, caller: Caller) -> bool:
        """Whether `root` is not there for `caller`: a token bound to a member, and a root that is not one
        of that member's (9.11)."""
        return (member := self._member(caller)) is not None and not self.hub.owns(member, root)

    def _new_address(self, doc: str, caller: Caller):
        """(root, path in it) of the file `create` is to make. Its root must be one the hub has, for
        every caller, and for a token bound to a member one of that member's (9.11); the rules of 8.3,
        and no hidden name, hold for the path. An absolute path is taken as it is written, inside the
        root's real path: it is not resolved, so a link on the way is left for the walk of
        `create_file` to refuse, as it is in `<root>/<path>`; a link into a root of another member's
        is answered first, as a path in no root."""
        doc = _named(doc)
        roots = self.hub.roots
        if "://" in doc:
            at = Address.parse(self._address_of_url(doc))
            root, rel = roots.get(at.root), at.rel
        elif os.path.isabs(doc):
            try:
                root = roots.lookup(Path(doc))
                if root is not None and self._hidden_root(root, caller):
                    root = None     # a root of another member's is none (9.11), before the link's message
                rel = Path(doc).relative_to(root.path).as_posix() if root is not None else ""
            except (OSError, ValueError):
                raise ToolError(f"{doc} {NOT_IN_A_ROOT} Name it `<root>/<path>`, or by the real "
                                "path of its folder.", "path") from None
        else:
            at = Address.parse(doc)
            root, rel = roots.get(at.root), at.rel
        if root is None or self._hidden_root(root, caller):
            raise ToolError(f"{doc} {NOT_IN_A_ROOT}", "path")     # a root of another member's is none (9.11)
        parts = rel.split("/")
        if (not rel.endswith(".md") or any(p in ("", ".", "..") or p.startswith(".") or "\0" in p
                                            for p in parts)):
            raise ToolError(f"{doc} cannot be made: a page is a .md file, and no part of its path is "
                            "empty, `..` or a hidden name.", "path")
        if in_git_dir(root.path / rel, root):
            raise ToolError(f"{doc} {NOT_IN_A_ROOT}", "path")
        return root, rel

    def _create(self, args: dict, caller: Caller):
        root, rel = self._new_address(args["doc"], caller)
        address, text = str(Address(root.name, rel)), _as_read(args["text"])
        if (member := self._member(caller)) is not None and not self.hub.member_owns(member, address):
            raise ToolError(f"{_named(args['doc'])} {NOT_IN_A_ROOT}", "path")     # a root of another member's
        self._check_size(text)
        _check_comments("", text)
        top = Path(os.path.realpath(root.path))
        try:
            # The owner is judged by the list's row for the address, which a sheaf already there may have: what
            # the path alone answers, walked as the write walks it, comes before every answer that judgement
            # shapes (the refusal, the size with the owner line), so none tells what is there, nor what a link
            # on the way points to.
            check_create(top, rel)
        except OSError as e:
            raise _not_made(address, e) from None
        text = self._owned(self._visible(text, None), address, caller)
        self._check_size(text)      # again: the owner `_owned` gave it is part of the page
        try:
            create_file(top, rel, text)
        except OSError as e:
            raise _not_made(address, e) from None
        self.hub.wrote(address)
        self.hub.committed(address, by=caller.display, what="create")
        return {"doc": address, "url": self.hub.url(address), "hash": md_hash(text)}

    def _update(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller)
        text, expected = _as_read(args["text"]), args["expected_hash"]
        if not HASH_RE.fullmatch(expected):
            raise ToolError("expected_hash is not a hash that `read` or `create` gave (16 hex digits).",
                            "hash")
        self._check_size(text)

        written = [text]

        def change(now_text):
            # Each check on the file as it is, under its lock; a sheaf the caller may not see first, so a
            # wrong hash does not tell it from no document (9.11).
            self._seen(now_text, address, caller, args["doc"])
            if md_hash(now_text) != expected:
                raise Stale(f"{address} has changed since that hash was read; read it again, make the "
                            "change on that text and send it with its hash.")
            _check_comments(now_text, text)
            written[0] = self._owned(self._visible(text, now_text), address, caller)
            self._check_size(written[0])
            return written[0]
        try:
            before, _ = update_file(self.hub.roots.document(address), change)
        except (OSError, UnicodeDecodeError, NotFound):
            raise ToolError(f"{address} could not be written.", "not written") from None
        text = written[0]
        if before != text:
            self.hub.wrote(address)
            self.hub.committed(address, by=caller.display, what="update")
        return {"doc": address, "url": self.hub.url(address), "hash": md_hash(text),
                "changed": before != text}

    def _visible(self, text: str, old: str | None) -> str:
        """In proxy mode, the text a door write puts on disk by the rule of visibility (9.11): the caller is
        an assistant, so its `visibility` and `shared` are not read, and a private source makes the sheaf
        its owner's alone. With no member to hide a page from, the text as sent."""
        if getattr(self.hub, "proxy", None) is None:
            return text
        # `sessions` is the hub's (9.12): an item of the box serves that transcript to every member of the
        # sheaf, and a door token is held by services that read untrusted text.
        # Judged on the text written, after for_door's rewrite: a line it takes out can join a line the reader
        # skipped to the list.
        out = visibility.for_door(text, old)
        was = visibility.front_matter(old).get("sessions", "") if old is not None else ""
        if visibility.front_matter(text).get("sessions", "") != was or visibility.front_matter(out).get("sessions", "") != was:
            raise ToolError("The text changes `sessions`, which only the hub writes; send it as `read` gave it"
                            + (" (a new page lists none)." if old is None else "."), "sessions")
        return out

    def _owned(self, text: str, address: str, caller: Caller) -> str:
        """`text`, a door write's text after `_visible`, when the sheaf it makes at `address` has an owner. A
        sheaf that is its owner's alone and that no member owns is open to nobody, the token that wrote it
        included, and no door write can mend it (9.11). So when no member owns it and it names no `owner`, a
        token bound to a member gives it that member's `short`; else the write is refused. One its issue's
        assignees alone own gets the `short` of one of them, so it stays theirs once the list does not poll the
        issue (#33). The key, which reads every file, writes it as `_visible` gave it (#30)."""
        if not self._judged(caller):
            return text
        fm = visibility.front_matter(text)
        if visibility.effective(fm) == "project":
            return text
        # an owner whose roots do not hold the sheaf cannot open it either (9.9)
        everyone = self.hub.members_owning(self.hub.proxy.members.values(), address)
        member = self._member(caller)
        owners = visibility.owner_of(fm, everyone, self.hub.assignees(address, fm))
        if owners and visibility.owner_of(fm, everyone):
            return text     # its `owner` owns it without the record, and stays as it is
        if owners:
            # Owned by its issue's assignees alone, who own it only while the list polls the issue: once it
            # does not, the `owner` is the owner, so it names one of them, the token's member first (#33).
            short = next((m.short for m in owners if m.short and member is not None and m.id == member.id),
                         next((m.short for m in owners if m.short), None))
            return visibility.set_keys(text, {"owner": short}) if short else text
        if member is not None and member.short and not visibility.text(fm, "owner"):
            text = visibility.set_keys(text, {"owner": member.short})
            fm = visibility.front_matter(text)
        if not visibility.owner_of(fm, everyone, self.hub.assignees(address, fm)):
            raise ToolError(f"{address} would be its owner's alone, with no member as its owner, and nobody could "
                            "open it: name a member's `short` as `owner`, or bind the token to a member.",
                            "no owner")
        return text


def _not_made(address: str, e: OSError) -> ToolError:
    """The answer to a `create` of `address` whose file `create_file` (or `check_create`) refused with `e`."""
    if isinstance(e, FileExistsError):
        return ToolError(f"{address} exists already; `create` makes a new page, and `update` changes one.",
                         "exists")
    if isinstance(e, FileNotFoundError):
        return ToolError(f"The folder of {address} does not exist; `create` makes no folder.", "no folder")
    if e.errno in (errno.ELOOP, errno.ENOTDIR):
        return ToolError(f"{address} could not be made: every folder on its way must be a folder of its root, "
                         "not a link or a file.", "link on the way")
    return ToolError(f"{address} could not be made ({e.strerror}).", "not written")


def _absent(doc: str) -> ToolError:
    """The answer to a `doc` that names no document, said the same for one the caller may not see (9.11)."""
    return ToolError(f"There is no document {_named(doc)} in a root of this hub; name it "
                     "`<root>/<path>`, by its page URL or by the absolute path of the .md.")


def _named(doc: str) -> str:
    """`doc` without the spaces around it, refused before anything looks at the disk when it is
    empty or not UTF-8. A name of bytes that are not UTF-8 comes as a lone surrogate (what Python's
    `email` makes of an undecodable header): the OS would make the file, and no URL can name it."""
    doc = doc.strip()
    if not doc:
        raise ToolError("doc is empty.")
    try:
        doc.encode("utf-8")
    except UnicodeEncodeError:
        raise ToolError("doc is not a name sheaf can serve: it is not UTF-8.", "path") from None
    return doc


def _as_read(text: str) -> str:
    """The text as sheaf reads a file back: every reader opens it with universal newlines, which
    take `\r\n` and a lone `\r` for a line end. A write is checked, made and hashed on this, so the
    comments checked are the comments read (a lone `\r` cannot carry one in or out of a fence)
    and the hash returned is the one `read` gives (SPEC 12)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _check_comments(before: str, after: str):
    """Refuse (ToolError) a text `after` whose comments are not exactly those of `before`: every
    one of them, with the same bytes, wherever it now sits, and no other. The same for comments
    that do not parse, save a line that starts with `-->`, which hides nothing and names nobody.
    So an update loses no thread, changes one only through `reply` and `resolve`, and text quoted
    into a page cannot plant one (SPEC 12, 9.7)."""
    was, now = rdc.parse(before), rdc.parse(after)
    old = {c.id: before[c.start:c.end] for c in was.comments}
    for c in now.comments:
        if c.id not in old:
            raise ToolError(f"The text adds comment {c.id} (line {c.line}); comments are written "
                            "on the page and answered with `reply`, never in the text.", "comments")
        if after[c.start:c.end] != old.pop(c.id):
            raise ToolError(f"The text changes comment {c.id} (line {c.line}); send it as `read` "
                            "gave it, and answer or resolve it with `reply` and `resolve`.", "comments")
    if old:
        raise ToolError(f"The text leaves out {'comment' if len(old) == 1 else 'comments'} "
                        f"{', '.join(old)}; send every comment of the file as `read` gave it.", "comments")
    left = [m for m in was.malformed if m.text.startswith("<!--")]
    for m in now.malformed:
        if m.text.startswith("<!--"):
            same = next((k for k in left if k.text == m.text), None)
            if same is None:
                raise ToolError(f"The text holds a comment that does not parse (line {m.line}, "
                                f"{m.reason}) that the file does not hold.", "comments")
            left.remove(same)
    if left:
        raise ToolError(f"The text leaves out the comment that does not parse at line {left[0].line} "
                        "of the file; send it as `read` gave it.", "comments")


def _unclosed_line(text: str, stripped: str) -> int:
    """The line of the first `<!--` of `text` that no comment closes; when removing comments
    made the opener (`<!<!-- x -->--`), its line in what was left."""
    closed = [m.span() for m in HTML_COMMENT_RE.finditer(text)]
    for m in re.finditer("<!--", text):
        if not any(a <= m.start() < b for a, b in closed):
            return text.count("\n", 0, m.start()) + 1
    return stripped.count("\n", 0, stripped.index("<!--")) + 1


# ── the stdio end: `sheaf mcp` ───────────────────────────────────────────────

def display_for(agent: str | None, environ=None) -> str:
    """The name replies are signed with (SPEC 12): the agent `--agent` names (a name sheaf knows
    gives its display name, any other is used as it is, once the hub would keep something of it),
    else the agent found in the environment (11.5), else `agent`."""
    if agent and agent.strip():
        cleaned = clean_display(agent)
        known = next((a for a in detect.TABLE if a.name == cleaned), None)
        name = known.display if known else cleaned
        if name:
            return name
    found = detect.detect(environ)
    return found.display if found else "agent"


class Stdio:
    """`post(raw) -> (status, body)` carries one message to the hub (client.DoorLink.post)."""

    def __init__(self, post, stdin, stdout, stderr):
        self.post, self.stdin, self.stdout, self.stderr = post, stdin, stdout, stderr

    def run(self) -> int:
        try:
            for line in self.stdin:
                raw = line.strip()
                if raw:
                    self._one(raw)
        except BrokenPipeError:             # the client closed its end: nothing more to say
            pass
        return 0

    def _one(self, raw: bytes):
        try:
            status, body = self.post(raw)
        except HubUnavailable as e:
            return self._fail(raw, str(e))
        if status == 202 or not body:
            return
        try:
            answer = json.loads(body)
        except ValueError:
            answer = None
        if isinstance(answer, dict) and answer.get("jsonrpc") == "2.0":
            return self._write(answer)
        what = answer.get("error") if isinstance(answer, dict) else None
        self._fail(raw, what if isinstance(what, str) and what else f"the hub answered {status}")

    def _fail(self, raw: bytes, why: str):
        """The hub could not take this message. A request is owed an answer, so it gets an
        error with its id; a notification gets nothing but a line on stderr."""
        print(f"sheaf mcp: {why}", file=self.stderr)
        try:
            message = json.loads(raw)
        except ValueError:
            message = None
        if isinstance(message, dict) and _is_id(message.get("id")):
            self._write(_error(message["id"], INTERNAL_ERROR, f"sheaf: {why}"))

    def _write(self, answer: dict):
        self.stdout.write(json.dumps(answer).encode("utf-8") + b"\n")
        self.stdout.flush()
