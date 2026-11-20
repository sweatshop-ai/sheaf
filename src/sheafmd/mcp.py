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
import contextlib
import errno
import json
import os
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, beneath, paths
from . import comments as rdc
from .agents import detect
from .hub.auth import clean_display
from .hub.client import HubUnavailable
from .hub.roots import Address, NotFound, address_of_url, in_git_dir, list_documents
from .agents import prompts
from .hub import loose, moves, place, targets, visibility
from .hub import repos as repos_mod
from .hub import waiting as waiting_mod
from .hub.state import TokenRow
from .render import COMMENT_RE as HTML_COMMENT_RE, strip_comments
from .beneath import Private
from .source import check_create, create_file, md_hash, now, update_beneath

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "sheaf keeps comment threads inside markdown files. Call `documents` first: it lists the "
    "documents with open comments and, under `tells`, what the person asked you to do (a Tell). "
    "Use `threads` to read what was asked on a document, `reply` to answer (role `action` after "
    "you acted on a Tell, `answer` when you only answer and changed nothing), and `resolve` when "
    "a thread is done. A Tell names the document and the comment id. Where you may work on pages, "
    "`read` gives a document's text and its hash, `create` makes a new page and `update` replaces "
    "the text of one, given the hash you read it with; keep every comment in the text you send.")

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
                       "closed (why, such as Permission denied); a root with more files than the hub lists "
                       "gets one too: root and more (how many were left out).",
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
            "text": {"type": "string", "description": "What you did, or your answer, in markdown: the page "
                                                     "renders paragraphs, lists, code and links."},
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
                       "does, inside a root the hub already has. With a bare file name (no root, no "
                       "slash) it makes a loose page in your own loose root, made on your first one, in "
                       "`folder` or else the month. It never replaces a file. The text holds no comment.",
        "properties": {
            "doc": {"type": "string", "description": "The new document: `<root>/<path>` ending in "
                                                     ".md, or the absolute path of the file to make; "
                                                     "or a bare `name.md` for a loose page."},
            "text": _TEXT,
            "folder": {"type": "string", "description": "A loose page only: the folder of your loose root "
                                                        "it goes in (`clients/blog`); the month, `YYYY-MM`, "
                                                        "when left out."},
            "keep": {"type": "boolean", "description": "A loose page only: true marks it never to be "
                                                       "archived."}},
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
    "move": {
        "description": "Put a loose page of yours in another folder of your loose root, named by its path "
                       "(`clients/blog`, made when it is not there; a folder with no page in it is gone). Its file name "
                       "stays. The old address forwards to the new one for ever, and the page's versions, comments, "
                       "marks and Share go with it; links to the old address are not rewritten. Only the owner moves a "
                       "page, and only within its root: a repo page moves by git. Answers the new `doc`, its `url` and "
                       "`hash`, and `moved_from`.",
        "properties": {
            "doc": _DOC,
            "folder": {"type": "string", "description": "The folder of your loose root the page goes in "
                                                        "(`clients/blog`): a path with no empty, `.`, `..` or hidden "
                                                        "part."}},
        "required": ["doc", "folder"]},
    "tells": {
        "description": "A laptop session asks for its Tells: those the person pressed on pages served here, for the "
                       "session id this token declared. Holds up to `wait` seconds (at most 25) when none waits and "
                       "answers `tells` (each with its doc, comment id and message); an empty list means ask again, "
                       "at once. A refusal says how long to wait before asking again.",
        "properties": {
            "session": {"type": "string", "description": "The session id; the X-Sheaf-Session header when left out."},
            "wait": {"type": "integer", "description": "Seconds to hold when nothing waits, 0 to 25 (default 25)."}},
        "required": []},
    "render_report": {
        "description": "Tell the tiroir that you work on a page of a git repo: the repo as `owner/name`, the page's "
                       "path in it and the commit you rendered. It sends no text. The tiroir clones the repo the "
                       "first time (blobless, sparse), holds the page's owner, and answers what it did.",
        "properties": {
            "repo": {"type": "string", "description": "The repo, `owner/name` on GitHub."},
            "path": {"type": "string", "description": "The page's path in the repo, ending in .md."},
            "commit": {"type": "string", "description": "The commit id the page was rendered at."}},
        "required": ["repo", "path", "commit"]},
}
PAGE_TOOLS = ("read", "create", "update", "move")    # the key, or a token made with --write (SPEC 9.7); a render report sends no text and needs only a member's token
WRITE_TOOLS = ("create", "update", "move")         # each call leaves a row in the diagnostics log (SPEC 15) and a line in the Write log (9.12)
SESSION_WRITES = ("create", "update", "move", "reply", "resolve")    # a write that names James's session to the hub (9.12)
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
    session: str | None = None      # James's session, from X-James-Session: set only for a token of `[list]`'s james_tokens (9.12)
    own_session: bool = False       # False on a james_tokens entry but the own one: its header is read, never resolved to an own session
    gone: object = None             # `gone()`: whether the caller closed the connection, for a call that waits (the Tells poll)
    declared: dict = field(default_factory=dict)    # what the caller declared in headers: session, host, link, chat (the Write log)

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
        if spec["type"] == "integer" and (type(v) is not int or not 0 <= v <= 25):
            raise ToolError(f"{k} must be a whole number of seconds, 0 to 25.")
        if "enum" in spec and v not in spec["enum"]:
            raise ToolError(f"{k} must be one of {', '.join(spec['enum'])}.")
    return args


def written_from(caller: Caller) -> tuple[str, dict]:
    """(place class, declared) of a door write, for the Write log, what the caller declared in its headers kept as declared.
    The box's James (a token of `[list]`'s james_tokens) is `tiroir`, and his `X-James-Session` the session when he declared
    no other; a caller that declared a chat id is a chat client; one that declared a session, a machine or a link, or that is
    the stdio door, is a laptop; any other is a chat client that declared nothing."""
    d = dict(caller.declared)
    if caller.session is not None:
        d["session"] = d.get("session") or caller.session
        return "tiroir", d
    laptop = caller.token is None or d.get("session") or d.get("host") or d.get("link")
    return ("chat client" if d.get("chat") or not laptop else "laptop"), d


class Door:
    def __init__(self, hub):
        self.hub = hub
        self.called = None      # called(caller, address or None) after each call of James's session (9.12)
        # real path -> ((inode, mtime_ns, ctime_ns, size), [(id, messages, last author)] of its open threads,
        # its front matter): a file is read again only when it changed, a write that kept its size and put
        # its time back included (SPEC 8.6, 9.11)
        self._open_threads: dict = {}
        self._tools = {"documents": self._documents, "threads": self._threads,
                       "reply": self._reply, "resolve": self._resolve, "read": self._read,
                       "create": self._create, "update": self._update, "move": self._move, "tells": self._session_tells,
                       "render_report": self._render_report}

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
            if name in SESSION_WRITES and isinstance(out, dict) and (declared := caller.declared.get("session")):
                out = {**out, "session": declared}      # the id the door recorded: the mod arms only for its own (9.14)
            if caller.session is not None and self.called is not None:
                self._tell_called(name, args, caller)
            return self._ok(id_, {"content": [{"type": "text", "text": json.dumps(self._told_out(out, caller), ensure_ascii=False)}],
                                  "isError": False})
        except ToolError as e:
            return self._ok(id_, {"content": [{"type": "text", "text": self._told_text(str(e), args, caller)}], "isError": True})
        except Exception:
            doc = args.get("doc") if isinstance(args.get("doc"), str) else None
            self.hub.record_exception("mcp-failed", doc, tool=name)
            return self._ok(id_, {"content": [{"type": "text", "text":
                                               "The hub failed on this call; the details are in `sheaf diag`."}],
                                  "isError": True})

    def _tell_called(self, name: str, args: dict, caller: Caller):
        """The hub hears of a call James's session made (9.12): which document a write went to, if one did. The
        call stands whatever the hub does with it."""
        address = None
        if name in SESSION_WRITES:
            try:
                address = self._address(args["doc"], caller)
            except (ToolError, KeyError, TypeError):
                address = None
        try:
            self.called(caller, address)
        except Exception:
            self.hub.record_exception("session-hook-failed", address, tool=name)

    # ── naming a document ────────────────────────────────────────────────────
    def _agent_wrote(self, address: str, caller: Caller):
        """A write made with an agent's token makes that agent the document's target: the member's own when the
        token acts for one, else the hub person's (SPEC 9.8). A read never gets here. The write stands whatever
        the hub does with it."""
        if caller.token is None or caller.token.client is None:
            return
        try:
            place, declared = written_from(caller)
            targets.note_write(self.hub, address, caller.token, self._member(caller),
                               session=declared.get("session") if place == "laptop" else None)
        except Exception:
            self.hub.record_exception("target-failed", address)

    def _ends_tells(self, address: str, cid: str, caller: Caller, role=None, resolved=False):
        """What a write ends of the Tells that wait for an agent (SPEC 9.8): an action reply by an agent's token ends
        its own Tell as done; a resolve ends every Tell of the thread. The write stands whatever this does."""
        try:
            if role == "action" and caller.token is not None and caller.token.client is not None:
                self.hub.waiting_tells.end(address, cid, "done", row=caller.token)
                session = caller.declared.get("session")
                if session:                      # the session's own reply, by the token that declared it (9.8)
                    self.hub.session_tells.end(address, cid, "done", row=caller.token, session=session)
            if resolved:
                self.hub.waiting_tells.end(address, cid, "cancelled", reason="resolved")
                self.hub.session_tells.end(address, cid, "cancelled", reason="resolved")
        except Exception:
            self.hub.record_exception("tell-end-failed", address)

    def _address(self, doc: str, caller: Caller, followed: list | None = None, write: bool = False) -> str:
        """`<root>/<path>` of the document `doc` names: that address itself, the URL of its page,
        or the absolute path of the .md. A caller who may add roots (the key) has the root of a
        path registered; a token (9.7) is held to the roots the hub already has. An address a page moved from is followed
        to where it is now (9.11), for the page's owner and for a caller bound to no member; the address it was is put in
        `followed`."""
        doc = _named(doc)
        if write and caller.may_write:
            # A write to a page of a clone that sleeps wakes it before the page is looked for (SPEC 13): for the page's owner
            # and a caller bound to no member, as the hub judges it, and only a caller whose token may write.
            member = self._member(caller)
            named = self._address_of_url(doc) if "://" in doc else doc      # a URL names its page by the address it holds
            self.hub.wake_for_write(named, None if member is None else visibility.owner_key(member))
        if "://" in doc:
            address = self._address_of_url(doc)
        elif os.path.isabs(doc):
            address = self._address_of_path(doc, caller)
        else:
            address = doc
        address = self.hub.unalias(address)         # the opaque name of a page Shared with the member (9.11)
        address = self._forwarded(address, caller, followed)
        with place.held(self.hub, address):         # a read, under the name's lock (9.11)
            try:
                self.hub.roots.document(address)
            except NotFound:
                raise self._asleep(address, caller) or _absent(doc) from None
            if self._judged(caller):
                # Before any other check of the call, so no answer tells a rectoverso the caller may not see from none;
                # each tool judges again on the text it reads.
                try:
                    judged = self.hub.judged(address)
                except (OSError, UnicodeDecodeError):
                    # Told only to a caller the last good read let see it, which knew of it already (9.11).
                    judged = self.hub.last_judged(address)
                    if judged is not None and self._sees(judged[0], address, caller):
                        raise _unreadable(address) from None
                    raise _absent(doc) from None
                if judged is None or not self._sees(judged[0], address, caller):
                    raise _absent(doc)
        return address

    def _asleep(self, address: str, caller: Caller) -> ToolError | None:
        """The answer to a page whose file is out because its clone sleeps (SPEC 13), told to a caller that may see the page:
        the one it was judged to see when the hub last read it, or the key. A write by the page's owner or a render report
        wakes the clone; a caller that may not write is told so instead of that the page does not exist. None for any other
        page and caller, which are answered as a document that is not there."""
        repo = self.hub.clone_of(address)
        if not repo or not self.hub.repos.sleeping(repo) or self.hub.judged(address) is None:     # a page the hub never read is none
            return None
        if self._judged(caller):
            member = self._member(caller)
            if member is None or not (self.hub.member_owns(member, address) and self.hub.visible(member, address)):
                return None
        return ToolError(self.hub.read_only_line(address), "asleep")

    def _forwarded(self, address: str, caller: Caller, followed: list | None) -> str:
        """`address`, or the address its Forward leads to when no page stands at it and the caller may be led there: the
        owner of the page the Forward leads to, or a caller that is bound to no member. Any other caller finds the address
        as it is, so it answers as an address never used."""
        try:
            self.hub.roots.document(address)
            return address
        except NotFound:
            pass
        to = self.hub.forwards.follow(address)
        if to is None:
            return address
        member = self._member(caller)
        if (far := self.hub.forwards.remote(address)) is not None:
            if member is not None and self.hub.loose_owner(address) != member.id:
                return address
            raise self._moved_away(address, far, caller, member)
        if member is not None and self.hub.loose_owner(to) != member.id:
            return address
        if followed is not None:
            followed.append(address)
        return to

    def _moved_away(self, address: str, far: dict, caller: Caller, member) -> ToolError:
        """The answer of a tool that names an address whose page went to another tiroir (ticket 20): nothing is written, and the
        sentence says who moved it, when, where it is, and what the caller does next, by the place it is calling from. The last line
        is the one the CLI reads."""
        where, declared = written_from(caller)
        self.hub.record("moved-knock", address, via="door", place=where, member=member.short if member else "", to=far["origin"])
        head = f"{address} was moved to {far['origin']} by {far['by']} on {far['at']} and is now {far['to']} there."
        if where == "laptop":
            tail = (f" `sheaf` sends it there itself when this laptop is connected to that shared Sheaf; otherwise run "
                    f"`sheaf connect {far['origin']}`.")
        else:
            tail = f" Ask {far['by']} to move it back, or for an account on that shared Sheaf."
        machine = json.dumps({"tiroir": far["origin"], "address": far["to"], "by": far["by"], "at": far["at"], "hash": far.get("hash", ""), "was": far.get("was", "")})
        return ToolError(f"{head}{tail}\nmoved: {machine}", "moved")

    def _judged(self, caller: Caller) -> bool:
        """Whether visibility (9.11) holds `caller`: a token, in proxy mode."""
        return caller.token is not None and getattr(self.hub, "proxy", None) is not None

    def _told_out(self, out, caller: Caller):
        """What a tool answers, with the page it names told to the caller as `_told` says: the tools work on the page's own
        address, which a member told of a Shared page by another never reads (9.11)."""
        if isinstance(out, dict) and isinstance(out.get("doc"), str) and isinstance(out.get("url"), str):
            return {**out, **self._told(out["doc"], caller)}
        return out

    def _told_text(self, text: str, args: dict, caller: Caller) -> str:
        """An error text of a call on a page, with the page's own address, which names the owner's folders, told as the
        caller is told of it."""
        doc = args.get("doc")
        if not isinstance(doc, str) or (member := self._member(caller)) is None:
            return text
        real = self.hub.unalias(doc)
        root = self.hub.roots.get(Address.parse(real).root)
        # Only a page Shared with the caller has an opaque name: a made-up name in another's root is none, and writes none.
        told = self.hub.alias(member, real) if root is not None and self.hub.shared_with(member, root, real) else doc
        return text.replace(real, told) if told != real else text

    def _told(self, address: str, caller: Caller) -> dict:
        """`doc` and `url` of the page at `address` as `caller` is told of it: a page Shared with its member by another is told
        under an opaque name, never the owner's folders (9.11)."""
        told = self.hub.alias(self._member(caller), address)
        return {"doc": told, "url": self.hub.url(told)}

    def _member(self, caller: Caller):
        """The member `caller` acts for (9.11): in proxy mode, the one whose `tokens` name its token; None for
        the key, a token bound to nobody, and every caller in loopback mode."""
        return self.hub.proxy.member_of_row(caller.token) if self._judged(caller) else None

    def _open(self, address: str):
        """The file of `address` opened beneath its root, the one open of the door (`sheafmd.beneath`): NotFound for
        what is not a file below it. What is judged is `place.opened_private` of this, and what is read is it."""
        root, rel = self.hub.roots.locate(address)
        try:
            return beneath.open_beneath(root.path, rel)
        except OSError:
            raise NotFound(address) from None

    def _sees(self, fm: dict, address: str, caller: Caller, owns: bool | None = None,
              opened=place.UNJUDGED) -> bool:
        """Whether `caller` may see the rectoverso at `address` whose front matter is `fm` (9.11). In proxy mode a
        token acts for the member whose `tokens` name it and sees what that member sees, in that member's
        roots only; a token bound to nobody sees every root (9.7) and no rectoverso that is its owner's alone. The
        key is the hub's own account, which reads every file. `owns`, when given, is `member_owns` for the
        token's member, already asked."""
        if not self._judged(caller):
            return True
        fm = self.hub.clone_fm(address, fm)             # a clone's page is judged as the page is (SPEC 14), by every door
        member = self._member(caller)
        if owns is None and member is not None:
            owns = self.hub.member_owns(member, address)
        if member is not None and not owns:
            return False
        if member is None:
            # rule A: no file of a private root is any unbound token's, whatever its front matter says
            return visibility.effective(fm) == "project" and place.private_member(self.hub, address, fm, opened) is None
        return self.hub.may_open(member, address, fm, opened)        # projects.toml grants a bound token's member (8.12)

    def _seen(self, text: str, address: str, caller: Caller, doc: str, opened=place.UNJUDGED) -> str:
        """`text`, the text of the document at `address`, when `caller` may see it; else the answer to a
        `doc` that names no document. `opened`: what `place.opened_private` gave for the file `text` was read from."""
        if not self._sees(visibility.front_matter(text), address, caller, opened=opened):
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
                try:
                    return roots.address(md, alias=lambda root, rel: place.alias(self.hub, root, rel))
                except NotFound:        # a file of a private root that no list name reaches
                    raise ToolError(f"{path} cannot be used as a document.") from None
            root = roots.lookup(md)
            if root is None or ((member := self._member(caller)) is not None and not self.hub.owns(member, root)):
                # a root of another member's is no root to a token bound to one (9.11)
                raise ToolError("A token cannot add a root, and the hub has no root that holds that file.")
            if roots.hidden(root):
                # A private root has no address (rule E): its member's token names the file by the list's name, any
                # other token, bound to nobody too, is told what it is told of a path in no root.
                named = place.alias(self.hub, root, Path(os.path.realpath(md)).relative_to(root.path).as_posix())
                if named is None or getattr(member, "id", None) != self.hub.private_roots[root.id]:
                    raise ToolError("A token cannot add a root, and the hub has no root that holds that file.")
                return named
            return str(Address(root.name, Path(os.path.realpath(md)).relative_to(root.path).as_posix()))
        except (OSError, ValueError) as e:
            # The key's caller runs as the hub's account and is told why. A token, held to the roots
            # the hub has (9.7), gets one answer for a path outside them, there or not.
            why = f" ({e.strerror})" if caller.may_add_roots and getattr(e, "strerror", None) else ""
            raise ToolError(f"{path} cannot be used as a document{why}.") from None

    def _comments(self, address: str, caller: Caller, doc: str):
        """The comments of the document as the file is now, not as a page was rendered. `doc` is how the
        caller named it, for the answer to one it may not see. Under the name's lock (9.11), as every read."""
        try:
            with place.held(self.hub, address), self._open(address) as op:
                text, private = op.text(), place.opened_private(self.hub, op)
        except (OSError, UnicodeDecodeError, NotFound):
            raise _unreadable(address) from None
        return rdc.parse(self._seen(text, address, caller, doc, private))

    def _comment(self, address: str, cid: str, caller: Caller, doc: str):
        c = self._comments(address, caller, doc).by_id(cid)
        if c is None:
            raise ToolError(f"There is no comment {cid} in {address}.")
        return c

    def _writable(self, address: str):
        """A page of a repo's clone with no save branch is not written, comments included (SPEC 14): the line says
        which `.sheaf.toml` line would change that."""
        if line := self.hub.read_only_line(address):
            raise ToolError(line, "read-only")

    def _write(self, address: str, caller: Caller, doc: str, op: str, fields: dict, role=None):
        """A change to one comment, and the agent of its token made the target (9.8) before the tabs hear
        of it. Through the document's Live Document when the hub has one,
        so open tabs hear of it at once and a Tell wait sees an action reply; straight into the
        file when the hub holds no page for it. Either way the caller's sight of it (9.11) is judged
        again on the file under its lock, so a rectoverso that closed since the check takes nothing. Both
        under the lock of the rectoverso's name (9.11), the file found again under it, so no move comes
        between finding the file and writing it."""
        self._writable(address)
        noted = False

        def note():
            nonlocal noted
            noted = True
            self._agent_wrote(address, caller)

        def guard(t, op=None):
            if op is None:                  # a page's own write reads the file by its path: the text must be the one
                with self._open(address) as seen:     # the file now opened beneath its root holds (9.11)
                    if seen.text() != t:
                        raise OSError(f"{address} is not the file that was opened")
                    return self._seen(t, address, caller, doc, place.opened_private(self.hub, seen))
            self._seen(t, address, caller, doc, place.opened_private(self.hub, op))
        try:
            with place.held(self.hub, address):
                # Through `Hub.entry` when the hub holds a page, which drops one bound to a root that no longer holds the file.
                entry = self.hub.entry(address) if address in self.hub.entries else None
                if entry is not None:
                    wrote = entry.live.comment(op, fields, None, by=caller.display, role=role, announce=True,
                                               guard=guard, before_announce=note)["wrote"]
                else:
                    top, rel = self.hub.roots.locate(address)
                    old, new = update_beneath(top.path, rel, lambda t, o: rdc.apply_op(
                        guard(t, o) or t, op, fields, caller.display, now(), role))
                    wrote = new != old
                if wrote:                               # a write that changed nothing commits nothing (8.11)
                    self.hub.committed(address, by=caller.display, what="comment")     # under the lock, as every write's
                if not noted:                           # no tab was told (none open, or nothing changed): still under the name
                    self._agent_wrote(address, caller)
        except rdc.AnchorError as e:
            raise ToolError(f"{e}.") from None
        except (OSError, UnicodeDecodeError, NotFound):
            raise ToolError(f"{address} could not be written.") from None

    # ── the tools ────────────────────────────────────────────────────────────
    def _open_in(self, address: str, whole: bool = False) -> tuple:
        """(open threads, front matter, mtime_ns, the member whose private root holds it, the text) of the file the rectoverso
        at `address` names, from one open beneath its root: all of it is of that descriptor (9.11). The text is None
        unless `whole`, which reads it from that descriptor even when the threads are kept."""
        top, rel = self.hub.where(address)
        with beneath.open_beneath(top, rel) as op:
            st = os.fstat(op.fd)
            private = place.opened_private(self.hub, op)
            key = (st.st_ino, st.st_mtime_ns, st.st_ctime_ns, st.st_size)
            cached = self._open_threads.get(address)
            if cached and cached[0] == key and not whole:
                return (*cached[1:], st.st_mtime_ns, private, None)
            text = op.text()
        threads = []
        if "comment id=" in text:
            for c in rdc.parse(text).comments:
                if c.status == "open":
                    last = c.display(c.replies[-1]) if c.replies else c.by
                    threads.append((c.id, 1 + len(c.replies), last))
        self._open_threads[address] = (key, threads, visibility.front_matter(text))
        return (*self._open_threads[address][1:], st.st_mtime_ns, private, text if whole else None)

    def _dot(self, address: str, unread: int, open_: int) -> str:
        """The dot of 8.6, as the index page gives it."""
        entry = self.hub.entries.get(address)
        if unread or (entry is not None and entry.live.session_question()):
            return "red"
        if self.hub.waiting(address):
            return "orange"
        return "blue" if open_ else "green"

    def _documents(self, args: dict, caller: Caller):
        hub = self.hub
        member = self._member(caller)
        if "root" in args:
            root = hub.roots.get(args["root"])
            if root is None or (member is not None and not hub.owns(member, root) and hub.giver(member, root) is None):
                raise ToolError(f"There is no root named {args['root']}.")
            wanted = [root]
        else:
            wanted = [r for r in hub.roots.listed()
                      if member is None or hub.owns(member, r) or hub.giver(member, r) is not None]
        rows, shut, left_out = [], [], {}
        agent = caller.token if caller.token is not None and caller.token.client is not None else None
        pending = hub.waiting_tells.pending(agent) if agent is not None else set()    # the Tells that wait for it (9.8)
        in_git = {}                             # (root, real folder) -> whether 8.2 keeps its files from the root
        owned = {}                              # (root, real folder) -> whether its files are the member's (9.11)
        reached = set()                         # the other members' loose roots that hold a page Shared with the member
        for root in wanted:
            giving = member is not None and not hub.owns(member, root)     # another's loose root: judged page by page
            # A root the hub cannot look into may hold what waits: said by name and why, never its folder (8.6). Of
            # another member's loose root, said to no one: what it holds is the owner's until Shared (9.11).
            if (why := root.closed()) is not None:
                if not giving:
                    shut.append({"root": root.name, "closed": why})
                continue
            if root.missing():
                continue
            placed = place.applies(hub, root.name)
            top = Path(os.path.realpath(root.path)) if placed else None
            # The files of a member's private root are listed to that member alone, under the list root's names (rule D).
            privates = [p for p in place.private_listed(hub, member) if p.closed() is None and not p.missing()] if placed else []
            files = []
            for src in (root, *privates):          # the hub's own lister (8.6, D15): its rules, its cap
                listing = list_documents(src)
                files += [(src, f.rel) for f in listing.docs]
                if listing.more:
                    left_out[root.name] = left_out.get(root.name, 0) + listing.more
            for src, found in files:
                # A rectoverso of the list's root is listed by its name (9.11), wherever its file is; a private path is
                # none. Each file is read under its name's lock, as every read.
                logical = place.logical(found) if placed else None
                with place.held(hub, f"{root.name}/{logical}") if logical else contextlib.nullcontext():
                    if src is not root:
                        rel = place.named_in(hub, root, src, found)
                    else:
                        rel = place.named(hub, root, top, found) if placed else found
                    if rel is None:
                        continue
                    address = str(Address(root.name, rel))
                    try:
                        path = hub.roots.resolve(address)          # never a file outside its root
                        folder = (src.name, path.parent)
                        if folder not in in_git:
                            in_git[folder] = in_git_dir(path, src)
                        if in_git[folder]:
                            continue                               # nor one in a git directory
                        threads, fm, mtime, private, text = self._open_in(address, whole=address in pending)
                    except (NotFound, OSError, UnicodeDecodeError):
                        continue
                # Whether the member owns a file asks git of its folder (8.2), and every file of a folder has the
                # same answer: asked once a folder, not once a file.
                if member is not None and (giving or folder not in owned):
                    owned[folder] = hub.member_owns(member, address)
                if not self._sees(fm, address, caller, owned.get(folder), private):
                    continue                                   # nor a rectoverso the caller may not see (9.11)
                if giving:
                    reached.add(root.name)
                tells = self._tells(address, text, agent, member) if text is not None else []
                if args.get("open_only", True) and not threads and not tells:
                    continue
                seen = hub.seen.get(address)
                unread = sum(1 for cid, n, last in threads if last != hub.person and n > seen.get(cid, 0))
                dot = self._dot(address, unread, len(threads))
                told = hub.alias(member, address) != address        # a page Shared with the member: no path on disk (9.9)
                rows.append((-1 if tells else DOT_ORDER[dot], -mtime, address,
                             {**self._told(address, caller), **({} if told else {"path": str(path)}),
                              "open": len(threads), "unread": unread, "dot": dot, "tells": tells}))
        if "root" in args and member is not None and not hub.owns(member, wanted[0]) and wanted[0].name not in reached:
            # Another member's loose root with nothing Shared with the caller is answered as a root that does not exist.
            raise ToolError(f"There is no root named {args['root']}.")
        return ([row[3] for row in sorted(rows, key=lambda r: r[:3])] + shut
                + [{"root": name, "more": n} for name, n in left_out.items()])

    def _tells(self, address: str, text: str, agent: TokenRow, member=None) -> list:
        """The Tells that wait for `agent` on this document, as they are listed to it (SPEC 9.8): the first listing
        marks each seen. Of `text`, read from the descriptor that was judged (9.11). Their words name the page as
        `member` is told of it, the opaque name of a Shared page, never the owner's folders."""
        try:
            got = rdc.parse(text)
        except (OSError, UnicodeDecodeError):
            return []
        links = self.hub.tell.links(address)
        told = self.hub.alias(member, address)
        return self.hub.waiting_tells.take(address, agent, got, lambda c, t: prompts.tell_agent(told, t["by"], c, links))

    def _session_tells(self, args: dict, caller: Caller):
        """The long-poll of a laptop session (SPEC 9.8): only the Tells queued for the session id this agent token
        declared, never for another token's session of the same id. The id is the header's, or the argument's when no
        header was sent; two that differ are refused."""
        if caller.token is None or caller.token.client is None or self._member(caller) is None:
            raise ToolError("Only a member's laptop token asks for the Tells of a session.")
        session, given = caller.declared.get("session") or "", args.get("session") or ""
        if given and session and given != session:
            raise ToolError("The session argument and the X-Sheaf-Session header name different sessions.")
        session = session or given
        if not session:
            raise ToolError("Name the session: the X-Sheaf-Session header, or the session argument.")
        tells = self.hub.session_tells
        try:
            got = tells.take(caller.token, session, float(args.get("wait", 25)), self._session_message(caller),
                             gone=caller.gone)
        except waiting_mod.Refused as r:
            raise ToolError(r.message, "busy" if r.status == 429 else "refused") from None
        return {"tells": got}

    def _session_message(self, caller: Caller):
        """`message(t)` for `SessionTells.take`: the words of a Tell, None when its thread is no longer open (it
        ends), False when the page cannot be read now (the Tell stays queued)."""
        hub, links = self.hub, {}

        def message(t):
            address = t["doc"]
            try:
                with place.held(hub, address):          # a read, under the name's lock (9.11)
                    opened = self._open_in(address, whole=True)
                text = opened[4]
                got = rdc.parse(text) if text is not None else None
            except (NotFound, OSError, UnicodeDecodeError):
                return False
            member = self._member(caller)
            if (member.id if member is not None else None) != t.get("member") or (
                    text is not None and not self._sees(visibility.front_matter(text), address, caller, opened=opened[3])):
                return False                    # the member no longer sees the page, or this token acts for another: it stays, unsaid
            c = got.by_id(t["thread"]) if got is not None else None
            if got is None or waiting_mod._stale(t, c):
                return None
            if address not in links:
                links[address] = hub.tell.links(address)
            return prompts.tell_agent(address, t["by"], c, links[address])
        return message

    def _threads(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller)
        status = args.get("status", "open")
        got = self._comments(address, caller, args["doc"])
        return {"doc": address, "url": self.hub.url(address),
                "comments": [{k: v for k, v in c.as_dict().items() if k != "block"}
                             for c in got.comments if status == "all" or c.status == status],
                "malformed": [{"line": m.line, "reason": m.reason} for m in got.malformed]}

    def _reply(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller, write=True)
        cid, text = args["id"], args["text"]
        if not text.strip():
            raise ToolError("text is empty.")
        self._comment(address, cid, caller, args["doc"])
        self._write(address, caller, args["doc"], "reply",
                    {"id": cid, "body": text, "resolve": args.get("resolve", False)},
                    role=args.get("role", "answer"))
        self._ends_tells(address, cid, caller, role=args.get("role", "answer"), resolved=bool(args.get("resolve")))
        c = self._comment(address, cid, caller, args["doc"])
        return {"id": cid, "status": c.status, "replies": c.as_dict()["replies"]}

    def _resolve(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller, write=True)
        cid = args["id"]
        if self._comment(address, cid, caller, args["doc"]).status != "resolved":
            self._write(address, caller, args["doc"], "status", {"id": cid, "status": "resolved"})
            self._ends_tells(address, cid, caller, resolved=True)
        return {"id": cid, "status": "resolved"}

    def _read(self, args: dict, caller: Caller):
        followed: list = []
        address = self._address(args["doc"], caller, followed)
        try:
            with place.held(self.hub, address), self._open(address) as op:     # no move between finding the file and reading it (9.11)
                text, private = op.text(), place.opened_private(self.hub, op)
        except (OSError, UnicodeDecodeError, NotFound):
            raise _unreadable(address) from None
        out = self._seen(text, address, caller, args["doc"], private)
        if not args.get("comments", True):
            out = strip_comments(text)
            if "<!--" in out:
                raise ToolError(f"{address} has a `<!--` that nothing closes, at line "
                                f"{_unclosed_line(text, out)}: the page shows nothing after it, "
                                "so its text without comments is not given.")
        return {"doc": address, "url": self.hub.url(address), "hash": md_hash(text), "text": out,
                **({"moved_from": followed[0]} if followed else {})}

    def _render_report(self, args: dict, caller: Caller) -> dict:
        """A render report (SPEC 13): the tiroir hears that the caller's member works on a repo page, and clones the
        repo the first time. No page is read or written; the answer says what the tiroir did."""
        repos = getattr(self.hub, "repos", None)
        if repos is None:
            return {"repo": args["repo"], "path": args["path"], "clone": repos_mod.NO_CLONES}
        member = self._member(caller)
        if member is None:
            raise ToolError("A render report is made with the token of a member: this one acts for nobody.", "no member")
        privates = [(visibility.owner_key(m), m.private_root) for m in self.hub.proxy.members.values() if m.private_root]
        try:
            return repos.report(visibility.owner_key(member), args["repo"], args["path"], args["commit"], privates, caller.declared)
        except repos_mod.Refused as e:
            raise ToolError(str(e), "refused") from None

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
        if name in WRITE_TOOLS and out.get("changed", True):
            self._logged_write(name, out["doc"], caller)
        sent = {"bytes": len(_as_read(args["text"]).encode("utf-8"))} if "text" in args else {}
        self.hub.record(f"door-{name}", out["doc"], outcome="written" if out.get("changed", True)
                        else "unchanged", hash=out["hash"], **sent, **who)
        return out

    def _logged_write(self, name: str, address: str, caller: Caller):
        place, declared = written_from(caller)
        self.hub.writes.add(address, caller.display, place, name, **declared)

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
                if root is not None and self.hub.roots.hidden(root):
                    # A private root has no address (rule E), and a rectoverso is not made in it by its path: to anyone
                    # but its member and the key a path in no root, to them the refusal of a private create (9.11).
                    if self._judged(caller) and place.in_private(self.hub, os.path.realpath(Path(doc))) not in (
                            None, getattr(self._member(caller), "id", None)):
                        raise ToolError(f"{doc} {NOT_IN_A_ROOT}", "path")
                    raise ToolError(f"{doc} cannot be made: {place.PRIVATE_PATH}.", "path")
                rel = Path(doc).relative_to(root.path).as_posix() if root is not None else ""
            except (OSError, ValueError):
                if not caller.may_add_roots:    # a token is told of a path no root holds as of one a root holds only by its spelling
                    raise ToolError(f"{doc} {NOT_IN_A_ROOT}", "path") from None
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
        if self._judged(caller) and place.in_private(self.hub, os.path.realpath(root.path / rel)) not in (
                None, getattr(self._member(caller), "id", None)):
            raise ToolError(f"{doc} {NOT_IN_A_ROOT}", "path")     # a private root is its member's alone (9.11): no probe, no write
        return root, rel

    def _loose(self, args: dict, caller: Caller):
        """The arguments of a create with no root, as the create of `<root>/<path>` they come to: the page's name in
        the member's loose root, in the folder named, else the month. Anything else goes on as it was given.
        (the arguments, and (member, root) of a root this call made, to take back if the create is refused)"""
        doc, folder = args["doc"], args.get("folder")
        bare = "/" not in doc and "\\" not in doc and "://" not in doc and not os.path.isabs(doc)
        if not bare and folder is None:
            if args.get("keep") is not None and not isinstance(args["keep"], bool):
                raise ToolError("keep must be true or false.", "keep")
            if args.get("keep"):
                raise ToolError("keep is for a loose page, made with a bare file name.", "path")
            return args, None
        if not bare:
            raise ToolError("folder is for a loose page: the document is then a bare file name, with no "
                            "root and no slash.", "path")
        if (member := self._member(caller)) is None:
            raise ToolError("a loose page belongs to a member: this caller acts for none.", "no member")
        try:
            rel = f"{loose.folder_path(folder)}/{doc}"
        except ValueError as e:
            raise ToolError(f"{e}.", "path") from None
        # What a create refuses by its name and its text alone, before a root or a folder is made for it.
        if not doc.endswith(".md") or doc.startswith(".") or "\0" in doc:
            raise ToolError(f"{doc} cannot be made: a page is a .md file, and no part of its path is empty, `..` or "
                            "a hidden name.", "path")
        text = _as_read(args["text"])
        self._check_size(text)
        _check_comments("", text)
        if args.get("keep"):
            self._keepable(member)
        try:
            root, fresh = self.hub.loose.root_for(member)
        except loose.Refused as e:
            raise ToolError(f"{e}.", "loose root") from None
        return {**args, "doc": str(Address(root.name, rel))}, (member, root) if fresh else None

    def _keepable(self, member):
        """Refuse (ToolError) a `keep` the member's loose root cannot mark, before the page is made."""
        held = self.hub.loose.known(member)
        if held is None:
            return
        try:
            loose.marks(held)
        except loose.Refused as e:
            raise ToolError(f"{e}.", "keep") from None

    def _create(self, args: dict, caller: Caller):
        given = args
        args, fresh = self._loose(args, caller)
        try:
            # A loose root's names have no lock of their own (`place.held` holds nothing there): a create of one takes the
            # moves' lock, so it is not made between a move's checks and its rename, nor reads a Forward half written.
            with moves.exclusive() if self._in_loose_root(args, caller) else contextlib.nullcontext():
                return self._created(given, args, caller)
        except BaseException:
            if fresh is not None:       # a refused create leaves no loose root it made behind
                self.hub.loose.drop(*fresh)
            raise

    def _in_loose_root(self, args: dict, caller: Caller) -> bool:
        """Whether the page `create` is to make ends in a loose root, whoever's, however its address is spelled: a bare name
        the door put there, `<loose-root>/<path>`, or the real path of the folder. A create `_created` refuses for its path
        takes no lock: it makes nothing."""
        try:
            root, _ = self._new_address(args["doc"], caller)
        except ToolError:
            return False
        return self.hub.loose.owner_of(root) is not None

    def _created(self, given: dict, args: dict, caller: Caller):
        root, rel = self._new_address(args["doc"], caller)
        address, text = str(Address(root.name, rel)), _as_read(args["text"])
        if (member := self._member(caller)) is not None and not (
                self.hub.owns(member, root) and self.hub.roots.lookup(root.path / rel) == root):
            # A root of another member's. Root ownership alone, not rule A: `_new_address` already refused a real path
            # inside a private root, and a list name a private root holds falls to `place.taken` below, as a shared one.
            raise ToolError(f"{_named(args['doc'])} {NOT_IN_A_ROOT}", "path")
        self._writable(address)         # a clone with no save branch is not written to, whoever's token
        if self.hub.forwards.follow(address) is not None:
            raise ToolError(f"{_named(args['doc'])} cannot be made: a page moved away from that address, and its "
                            "Forward stays. Pick another name or folder.", "moved")
        placed = place.applies(self.hub, root.name)
        if placed and place.names_private(rel):
            raise ToolError(f"{_named(args['doc'])} cannot be made: the hub places owner-only rectoversos itself: name "
                            "`<client>/<project>/<name>.md`.", "path")
        try:
            if placed and place.undecided(self.hub, rel):      # a private root that cannot be looked at may hold the name
                raise NotFound(rel)
            held = place.in_private(self.hub, os.path.realpath(self.hub.file(address))) is not None
        except NotFound:          # a name two roots hold, or a private root that cannot be looked at (rule B)
            raise ToolError(f"{_named(args['doc'])} {NOT_IN_A_ROOT}", "path") from None
        if member is not None and not self.hub.granted(member, address, by_name=held):
            raise ToolError(f"{_named(args['doc'])} {NOT_IN_A_ROOT}", "path")     # a project not theirs (8.12)
        self._check_size(text)
        _check_comments("", text)
        top = Path(os.path.realpath(root.path))
        name = place.logical(rel) if placed else None
        # The name's lock (9.11) from the first look at its homes to the file made: a create of the same name, or a
        # move, that comes meanwhile waits, and then finds the name taken.
        with place.held(self.hub, address):
            try:
                made = []
                if args is not given:       # a loose page's folders are made, each opened without following a link
                    made = _missing_folders(top, rel)
                    try:
                        os.close(place.make_folders(top, rel, place.judge_for(self.hub, root))[0])
                    except Private:
                        _unmake(top, made)
                        raise
                    except OSError as e:
                        _unmake(top, made)
                        raise _not_made(address, e) from None
                try:
                    text = self._make(root, top, rel, name, address, text, caller)
                except BaseException:
                    _unmake(top, made)      # the folders this create made go with it
                    raise
                if args.get("keep"):        # under the name's lock with the write: the page is never there unmarked
                    try:
                        loose.keep(root.path, rel)
                    except loose.Refused as e:
                        with contextlib.suppress(OSError):
                            os.unlink(top / rel)        # made a moment ago under this name's lock: take it back
                        self.hub.writes.told(address)
                        _unmake(top, made)
                        raise ToolError(f"{address} was not made: {e}.", "keep") from None
            except Private:         # the root's folder, as opened, is a private root's: answered as a path in no root
                raise ToolError(f"{_named(args['doc'])} {NOT_IN_A_ROOT}", "path") from None
            self._agent_wrote(address, caller)          # before the tabs and indexes hear of it
            self.hub.wrote(address)
            self.hub.committed(address, by=caller.display, what="create")
        out = {"doc": address, "url": self.hub.url(address), "hash": md_hash(text)}
        if visibility.audience(_as_read(args["text"])) is not None and visibility.audience(text) is None:
            out["note"] = ("The page holds private work, so it is not Shared: its Share line was written unticked. "
                           "Its owner shares it from the page or the Sheaf.")
        return out

    def _make(self, root, top: Path, rel: str, name: str | None, address: str, text: str, caller: Caller):
        """The file of a create, at its home when the hub places it (9.11): the text written. The rectoverso's address is
        its name wherever its file is."""
        judge = place.judge_for(self.hub, root)
        try:
            # The owner is judged by the list's row for the address, which a rectoverso already there may have: what
            # the path alone answers, walked as the write walks it, comes before every answer that judgement
            # shapes (the refusal, the size with the owner line), so none tells what is there, nor what a link
            # on the way points to.
            check_create(top, rel, judge)
            # A rectoverso's name is taken by its file at home and at every private home (9.11), whoever's it is.
            if name is not None and place.taken(self.hub, root, name):
                raise FileExistsError(errno.EEXIST, "File exists", rel)
        except Private:
            raise
        except OSError as e:
            raise _not_made(address, e) from None
        # Every create, open or not, tells the list its address has no file now: the row of a rectoverso that went
        # there would judge the new one (its owner on a later update, its row on the page) until the next poll (#34).
        self.hub.assignees(address, {})
        text = self._door_text(text, None, address, caller)
        self._check_size(text)      # again: the owner `_owned` gave it is part of the page
        # Made at its home (9.11), so no file, and no commit, ever holds a rectoverso that is its owner's alone at the
        # project's path: one with no home is not made.
        private_home = False
        if name is not None and (found := place.home_in(self.hub, root, name, text)) != (root, rel):
            if found is None:
                raise ToolError(f"{address} cannot be made: {place.NO_SHORT}, so it would have no home.", "path")
            home_root, home = found
            if home_root.id != root.id:
                # Rule F: its home is a private root, made there only for the token bound to that root's member. The
                # owner is the one the text now names (`_owned` has given it), so assignees open no root to a caller.
                member = self._member(caller)
                if member is None or self.hub.private_roots.get(home_root.id) != member.id:
                    raise ToolError(f"{address} cannot be made: {place.PRIVATE_ROOT}.", "path")
                root, top, judge = home_root, Path(os.path.realpath(home_root.path)), place.judge_home(self.hub, home_root)
                private_home = True     # the member's repo may not hold the project's folder yet: made as a private folder is
            if place.ignores(top, home):
                # Made there, it would be untracked and leave the listing (8.6): refused as a move there is.
                raise ToolError(f"{address} cannot be made: {place.IGNORED}, so it would have no home.", "path")
            rel = home
        self.hub.writes.expect_own(address, md_hash(text))     # a look at the file before `wrote()` is not a disk write
        try:
            if name is not None and (rel != name or private_home):    # the folders, walked as create_file walks
                with place.folders_lock(top, name):     # so no move's tidying takes them before the file is in
                    os.close(place.make_folders(top, rel, judge)[0])
                    create_file(top, rel, text, judge)
            else:
                create_file(top, rel, text, judge)
        except BaseException as e:
            self.hub.writes.told(address)       # a page that was not made leaves nothing to expect
            if isinstance(e, Private) or not isinstance(e, OSError):
                raise
            raise _not_made(address, e) from None
        return text

    def _update(self, args: dict, caller: Caller):
        followed: list = []
        address = self._address(args["doc"], caller, followed, write=True)
        self._writable(address)
        text, expected = _as_read(args["text"]), args["expected_hash"]
        if not HASH_RE.fullmatch(expected):
            raise ToolError("expected_hash is not a hash that `read` or `create` gave (16 hex digits).",
                            "hash")
        self._check_size(text)
        # The name's lock (9.11) from finding the file to the commit: move, write, render, commit, one operation, so
        # no poll moves the file in between and no other writer's commit takes this write.
        with place.held(self.hub, address):
            moved = []
            try:
                before, text, gone = self._updated(address, args, text, expected, caller, moved)
                if before != text or gone:          # a text that changed nothing may still have moved the file
                    moved.clear()
                    self.hub.committed(address, by=caller.display, what="update", gone=gone)
            finally:
                if moved:                           # moved, then failed before its commit: the move is committed
                    self.hub.committed(address, by=caller.display, what="update", gone=moved.pop())
        return {"doc": address, "url": self.hub.url(address), "hash": md_hash(text), "changed": before != text,
                **({"moved_from": followed[0]} if followed else {})}

    def _move(self, args: dict, caller: Caller):
        address = self._address(args["doc"], caller, write=True)
        if (member := self._member(caller)) is None:
            raise ToolError("a loose page belongs to a member: this caller acts for none.", "no member")
        try:
            new = moves.move_page(self.hub, member, address, args["folder"])
        except moves.Refused as r:
            if r.status == 404:
                raise _absent(args["doc"]) from None
            raise ToolError(r.message, "owner" if r.status == 403 else "move") from None
        text = self.hub.file(new).read_text(encoding="utf-8", errors="replace")
        return {"doc": new, "url": self.hub.url(new), "hash": md_hash(text), "moved_from": address}

    def _updated(self, address: str, args: dict, text: str, expected: str, caller: Caller, moved: list):
        """The write of an update, and the rectoverso's file moved to its home (9.11): (the text before, the text
        written, the path in the root the file left or None). A move `ahead` makes is put in `moved` as it is made,
        so the caller commits it whatever comes after."""
        written = [text]

        def change(now_text, opened):
            # Each check on the file as it is, under its lock; a rectoverso the caller may not see first, so a
            # wrong hash does not tell it from no document (9.11). Judged on the file this open holds.
            self._seen(now_text, address, caller, args["doc"], place.opened_private(self.hub, opened))
            if md_hash(now_text) != expected:
                raise Stale(f"{address} has changed since that hash was read; read it again, make the "
                            "change on that text and send it with its hash.")
            _check_comments(now_text, text)
            written[0] = self._door_text(text, now_text, address, caller)
            self._check_size(written[0])
            self.hub.writes.expect_own(address, md_hash(written[0]))       # a look at the file before `wrote()` is not a disk write
            return written[0]

        def move(now_text, new):
            # A text that opens or closes the rectoverso moves its file to its home before it is written there (9.11); one
            # that cannot go there is not written.
            try:
                gone = place.ahead(self.hub, address, now_text, new)
            except place.Refused as ex:
                raise ToolError(f"{address} was not written: {ex.why}, so it could not go to its home.",
                                "not written") from None
            if gone is None:
                return None
            moved.append(gone)
            return self.hub.file(address, placed=True)
        try:
            top, rel = self.hub.roots.locate(address)
            try:
                before, _ = update_beneath(top.path, rel, change, move=move)
            except BaseException:
                if address in self.hub.writes._own:     # a write that failed after it was expected leaves nothing to expect
                    self.hub.writes.told(address)
                raise
        except (OSError, UnicodeDecodeError, NotFound):
            raise ToolError(f"{address} could not be written.", "not written") from None
        text = written[0]
        if before != text:
            self._agent_wrote(address, caller)          # before the tabs hear of it (9.8)
            self.hub.wrote(address)
        # A text that changed nothing may still move the file to its home; its address stays.
        return before, text, moved[0] if moved else place.place(self.hub, address, commit=False)

    def _door_text(self, text: str, old: str | None, address: str, caller: Caller) -> str:
        """The text a door write puts on disk: `_visible`'s, with the `owner` `_owned` gives it. `_owned` rewrites
        the front matter with `set_keys`, which can join a line the reader gave another key to `sessions`, so
        `sessions` is judged again on what it gives (#36)."""
        seen = self._visible(text, old)
        out = self._shared(self._owned(seen, address, caller), old, caller, address)
        sessions = visibility.front_matter(seen).get("sessions", "")    # the old value: `_visible` saw to that
        if out != seen and visibility.front_matter(out).get("sessions", "") != sessions:
            raise _sessions_changed(old)
        return out

    def _shared(self, text: str, old: str | None, caller: Caller, address: str) -> str:
        """`text` once the rule of Share holds for a door write (9.11). The agent may Share only on `create` of a new
        page: a ticked Share line there opens the page, and its `shared` line says which agent did, for the row.
        An `update` never opens a page to anyone it was not open to, whoever the token's member is, so text an agent
        read cannot open a page that holds private work; closing a Share, or naming fewer members, opens nothing.
        On a client tiroir the agent may Share only with its agency members, never plain (9.11), and an update adds no
        Share line and changes none: the lines it may send back are among the ones it was sent."""
        if getattr(self.hub, "proxy", None) is None:
            return text
        now = visibility.audience(text)
        cfg = self.hub.proxy
        if cfg.client:
            if old is None and not visibility.only_names_in(now, {m.short.casefold() for m in cfg.members.values()
                                                                  if m.agency and m.short}):
                raise ToolError("On this tiroir an agent may only Share with agency members, by name: `Share with <name>`. "
                                "A plain Share, or a name that is not an agency member's, is the member's own act, "
                                "from the page or the Sheaf.", "share")
            if old is not None and Counter(visibility.share_lines(text)) - Counter(visibility.share_lines(old)):
                # every line sent back is one `read` gave, as the parser reads it: removing or reordering opens nothing
                raise ToolError("An update cannot add or change a Share line on this tiroir. Send the text with its Share "
                                "lines as `read` gave them.", "share")
        if old is not None:
            if visibility.widens(visibility.audience(old), now):
                raise ToolError("An update cannot Share a page, nor open it to more members: only its owner does, from "
                                "the page or the Sheaf. Send the text with its Share lines as `read` gave them.", "share")
            if self.hub.opens_more(address, old, text):
                # the hub's own audience before and after, not the Share lines: taking off the private source that kept a
                # hand-ticked line closed opens the page as a Share would
                raise ToolError("An update cannot Share a page, nor open it to more members: only its owner does, from "
                                "the page or the Sheaf. Send the text with its Share lines as `read` gave them.", "share")
            m = self._member(caller)
            if m is not None and visibility.share_lines(old) != visibility.share_lines(text) \
                    and not self.hub.is_owner(m, address, visibility.front_matter(old)):
                raise ToolError("Who a page is Shared with is its owner's alone: an update from a token of another member "
                                "cannot narrow or withdraw it. Send the text with its Share lines as `read` gave them.", "share")
            if visibility.narrows(visibility.audience(old), now) and self.hub.loose_owner(address) is None:
                # Naming fewer members closes the page at once to every member no longer named: names-only form (9.11).
                return visibility.names_only(text)
            return text
        if now is None:
            return text
        if visibility.effective(visibility.front_matter(text)) == "owner":
            return visibility.without_ticked_share(text)    # a private source keeps the page its owner's whatever its text ticks (#40): the line is not left ticked
        return visibility.set_keys(text, {"visibility": "project",
                                          "shared": f"agent:{caller.display} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"})

    def _visible(self, text: str, old: str | None) -> str:
        """In proxy mode, the text a door write puts on disk by the rule of visibility (9.11): the caller is
        an assistant, so its `visibility` and `shared` are not read, and a private source makes the rectoverso
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
            raise _sessions_changed(old)
        return out

    def _owned(self, text: str, address: str, caller: Caller) -> str:
        """`text`, a door write's text after `_visible`, when the rectoverso it makes at `address` has an owner. A
        sheaf that is its owner's alone and that no member owns is open to nobody, the token that wrote it
        included, and no door write can mend it (9.11). So when no member owns it and it names no `owner`, a
        token bound to a member gives it that member's `short`; else the write is refused. One its issue's
        assignees alone own gets the `short` of one of them, so it stays theirs once the list no longer knows the
        issue (#33). The key, which reads every file, writes it as `_visible` gave it (#30)."""
        if not self._judged(caller):
            return text
        fm = visibility.front_matter(text)
        if visibility.effective(fm) == "project":
            return text
        if (loose := self.hub.loose_owner(address)) is not None:
            # A loose page is owned by the member whose loose root holds it (9.11), with no `owner` line: no other member's
            # write names an owner there, and the text stays as it is.
            return text
        # an owner whose roots do not hold the rectoverso cannot open it either (9.9)
        everyone = self.hub.members_owning(self.hub.proxy.members.values(), address)
        member = self._member(caller)
        owners = visibility.owner_of(fm, everyone, self.hub.assignees(address, fm))
        by_owner_line = visibility.owner_of(fm, everyone)
        if owners and by_owner_line:
            return text     # its `owner` owns it without the record, and stays as it is
        if owners:
            # Owned by its issue's assignees alone, who own it only while the list knows the issue: once it no
            # longer does, the `owner` is the owner, so it names one of them, the token's member first (#33).
            # An assignee with no `short` cannot be named, and the text stays as it is.
            named = [m for m in owners if m.short]
            mine = [m for m in named if member is not None and m.id == member.id]
            return visibility.set_keys(text, {"owner": (mine or named)[0].short}) if named else text
        if member is not None and member.short and not visibility.text(fm, "owner"):
            text = visibility.set_keys(text, {"owner": member.short})
            fm = visibility.front_matter(text)
        if not visibility.owner_of(fm, everyone, self.hub.assignees(address, fm)):
            raise ToolError(f"{address} would be its owner's alone, with no member as its owner, and nobody could "
                            "open it: name a member's `short` as `owner`, or bind the token to a member.",
                            "no owner")
        return text


def _sessions_changed(old: str | None) -> ToolError:
    """The answer to a door write whose text, as written, changes `sessions` (9.12); `old` is None for a create."""
    return ToolError("The text changes `sessions`, which only the hub writes; send it as `read` gave it"
                     + (" (a new page lists none)." if old is None else "."), "sessions")


def _missing_folders(top: Path, rel: str) -> list:
    """The folders on the way to `rel` under `top` that are not there yet, outermost first: what a create that walks
    them is the one to make, and to take back if it is refused. A link or a file on the way is none of these."""
    out, at = [], Path(top)
    for part in rel.split("/")[:-1]:
        at = at / part
        if not os.path.lexists(at):
            out.append(at)
    return out


def _unmake(top: Path, made: list):
    """Take back the folders `_missing_folders` named, innermost first, each only if it is empty."""
    for folder in reversed(made):
        with contextlib.suppress(OSError):
            os.rmdir(folder)


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


def _unreadable(address: str) -> ToolError:
    """The answer to a document whose file is there but cannot be read, or not as UTF-8: in proxy mode only to a
    token that may see it (9.11), so a client can tell it from `_absent`."""
    return ToolError(f"{address} cannot be read.", "unreadable")


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
