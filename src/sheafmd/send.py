"""
sheafmd.send — `sheaf FILE.md` on a connected laptop sends a loose page to the member's tiroir (SPEC 13).

    sheaf FILE.md [--folder NAME] [--keep] [--local]
    sheaf pull FILE.md

A page outside any git repo is a loose page. When the laptop holds a credential for its tiroir (the root's
`.sheaf.toml` `tiroir`, else the laptop's default in config.toml), the page is sent through the tiroir's library door:
`create` the first time, `update` with the hash the tiroir last gave after. The CLI's state folder keeps, per local
path, the tiroir, the page's address, that hash and the hash of the local text it was made from; nothing is written
beside the file. An `update` the tiroir refuses because its text moved on leaves that text as `FILE.tiroir.md`, records
it as read and fails, so that the agent merges the two and runs the command again. `sheaf pull` writes the tiroir's
latest text into the file, and never over an edit made here. Every write declares the session, the machine and the
Remote Control link (SPEC 9.12), as declared and never verified.

A tiroir that does not answer the messages before the write in 5 s each, or answers 5xx, leaves the page to the laptop hub with one loud
line; nothing is queued, no process is left, and the next run sends `create` or `update` as the state says (a 401 or a
403 fails with no fallback).

With `--local`, with no credential, or for a page in a git repo, nothing is sent: `send_page` answers None and the
caller renders on the laptop hub as before. The network is two functions, `post` and `get`, which a test replaces; the
keyring is `connect.system_store()`, which a test replaces too.
"""
import argparse
import dataclasses
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import config, connect, paths
from .agents.claude_code import config_dir_of
from .agents.detect import detect, session_id
from .atomic import write_text_atomic
from .hub import repos as repos_mod
from .hub.roots import url_path
from .hub.state import file_locked
from .hub.writelog import declared_link
from .source import md_hash

EXIT_OK, EXIT_FAILED = 0, 1
TIMEOUT = 15.0
LONG_POLL_TIMEOUT = 35.0   # a `tells` call the door holds for up to 25 s
CONNECT_TIMEOUT = 5.0   # the messages before a tool call (`initialize` and its notice): a tiroir that does not answer them is not there
STATE_FILE = "sends.json"
PROTOCOL = "2025-06-18"

COMMAND_HELP: dict = {}


class SendError(Exception):
    """A send that stops: the message is one sentence a person reads, and says what was left unchanged."""


class TokenRefused(SendError):
    """The door refused the token (401, 403): the one answer that never falls back to rendering here."""


class Moved(SendError):
    """The page was moved to another shared Sheaf by its owner (ticket 20): the door of the old one wrote nothing and says where
    it went. `hash` is the text that landed there, `was` the text that left (empty when the old tiroir did not say)."""

    def __init__(self, sentence: str, origin: str, address: str, hash_: str, was: str = ""):
        super().__init__(sentence)
        self.origin, self.address, self.hash, self.was = origin, address, hash_, was


def _moved_part(text: str) -> Moved | None:
    """The `moved:` line the door puts last in its answer for a page that went to another tiroir, as a `Moved`."""
    head, _, last = text.rstrip().rpartition("\nmoved: ")
    try:
        got = json.loads(last)
        origin, address = got["tiroir"], got["address"]
    except (ValueError, KeyError, TypeError):
        return None
    if not (head and isinstance(origin, str) and isinstance(address, str)):
        return None
    return Moved(head, origin, address, got["hash"] if isinstance(got.get("hash"), str) else "",
                 got["was"] if isinstance(got.get("was"), str) else "")


class Unreachable(SendError):
    """The tiroir did not answer, or answered 5xx: the caller serves the page from the laptop hub and says so."""


# ── the network: the two places a test stands in for the tiroir ─────────────

def _refusal_text(e: urllib.error.HTTPError) -> str:
    """What a 4xx answer says, as one short printable line (the door's own words), or "" when it says nothing usable."""
    try:
        raw = e.read(1024)
    except (OSError, ValueError):
        return ""
    line = " ".join(raw.decode("utf-8", "replace").split())
    return "".join(c for c in line if c.isprintable())[:200]


def _request(req, timeout: float = TIMEOUT) -> tuple[int, dict | None, dict]:
    try:
        with connect._NO_REDIRECT.open(req, timeout=timeout) as r:
            raw, status, headers = r.read(8 << 20), r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise Unreachable(f"{req.full_url.split('/', 3)[2]} answered with an error ({e.code}). "
                              "Nothing was sent.") from None
        return e.code, None, {"refusal": _refusal_text(e)}
    except (urllib.error.URLError, OSError) as e:
        # A URLError carries its cause as `reason`; an SSLError read from the socket is its own cause (its `reason` is a word).
        why = e.reason if isinstance(e, urllib.error.URLError) else e
        if isinstance(why, ssl.SSLCertVerificationError):       # a certificate it cannot trust is no outage; a reset is
            raise SendError(f"cannot trust {req.full_url.split('/', 3)[2]}: {why}. "
                            "Nothing was sent.") from None
        raise Unreachable(f"cannot reach {req.full_url.split('/', 3)[2]}: {why}. "
                        "Nothing was sent.") from None
    return status, connect._json_of(raw.decode("utf-8", "replace")) if raw.strip() else None, headers


def post(url: str, token: str, message: dict, headers: dict) -> tuple[int, dict | None, dict]:
    """(status, parsed JSON or None, response headers) of one JSON-RPC message sent to the door with the bearer."""
    req = urllib.request.Request(url, json.dumps(message).encode(), {
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream", **headers}, method="POST")
    if message.get("method") != "tools/call":
        return _request(req, CONNECT_TIMEOUT)
    return _request(req, LONG_POLL_TIMEOUT if (message.get("params") or {}).get("name") == "tells" else TIMEOUT)


def get(url: str, token: str) -> tuple[int, dict | None, dict]:
    return _request(urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET"))


def machine() -> str:
    return socket.gethostname()


# ── what a write declares ────────────────────────────────────────────────────

def remote_link(environ, session: str) -> str:
    """The Remote Control link of the session `session`, from the agent's own record of it, when it holds one: a web
    address under a key that names the remote. Anything else is no link."""
    try:
        records = sorted((config_dir_of(environ) / "sessions").glob("*.json"))
    except OSError:
        return ""
    for f in records:
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("sessionId") == session:
            for key, value in rec.items():
                if "remote" in key.lower() and isinstance(value, str) and (link := declared_link(value)):
                    return link
    return ""


MAX_ANCESTORS = 64      # a walk this deep has gone past any process tree
PS_TIMEOUT = 2.0


def ps_parent(pid: int) -> int:
    """The parent of `pid` from `ps -o ppid= -p PID` (no shell), for a system with no /proc; raises OSError when ps fails."""
    try:
        done = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True, timeout=PS_TIMEOUT)
        if done.returncode != 0:
            raise OSError(f"ps exited {done.returncode}")
        return int(done.stdout.strip())
    except (subprocess.SubprocessError, ValueError) as e:
        raise OSError(str(e)) from None


def ancestor_pids(pid: int | None = None, proc: Path = Path("/proc"), ps=ps_parent) -> list[int]:
    """`pid` and its parents up to init: each parent from `proc`/PID/stat, else from `ps`; the walk stops at a process
    neither can read, at a loop, and after MAX_ANCESTORS."""
    pid = os.getpid() if pid is None else pid
    chain: list[int] = []
    while pid > 0 and pid not in chain and len(chain) < MAX_ANCESTORS:
        chain.append(pid)
        try:
            stat = (proc / str(pid) / "stat").read_text(encoding="utf-8", errors="replace")
            pid = int(stat.rpartition(")")[2].split()[1])      # after the name, which may hold spaces and brackets: state, ppid
        except (OSError, ValueError, IndexError):
            try:
                pid = ps(pid)
            except OSError:
                break
    return chain


def registry_session(environ=None) -> str | None:
    """The session id of the Claude Code that runs this process, from its own record `<config>/sessions/<pid>.json` of the
    nearest ancestor that has one; None when no ancestor has. A headersHelper gets no `CLAUDE_CODE_SESSION_ID` (live check,
    2026-11-16), and the variable it may inherit is some parent shell's, so the helper never reads it."""
    environ = os.environ if environ is None else environ
    sessions = config_dir_of(environ) / "sessions"
    for pid in ancestor_pids():
        try:
            rec = json.loads((sessions / f"{pid}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and isinstance(rec.get("sessionId"), str) and rec["sessionId"].strip():
            return rec["sessionId"].strip()
    return None


def declared(environ=None, session=...) -> dict:
    """The request headers a send declares itself with: session, machine, Remote Control link; only those it has.
    `session` replaces the agent's variable (the headersHelper's, from the registry)."""
    environ = os.environ if environ is None else environ
    session = session_id(environ) if session is ... else session
    out = {"X-Sheaf-Host": machine()}
    if session:
        out["X-Sheaf-Session"] = session
        if link := remote_link(environ, session):
            out["X-Sheaf-Link"] = link
    return {k: v for k, v in out.items() if v and v.isprintable() and len(v) <= 512}


# ── the door ─────────────────────────────────────────────────────────────────

# What the caller reads from the result of a tool that did not fail: each must be text.
_RESULT_TEXT = {"create": ("doc", "hash"), "update": ("doc", "hash"), "read": ("hash", "text")}


# The hub's tools that the CLI calls: the names a door may list under a prefix.
_HUB_TOOLS = ("create", "update", "read", "render_report")


class Door:
    """One tiroir's library door, with the token: `initialize` first (a door may keep a session), then each tool call."""

    def __init__(self, origin: str, token: str, headers: dict):
        self.origin, self.token, self.headers, self.n = origin, token, dict(headers), 0
        self.started = False
        self.names: dict[str, str] | None = None     # the tool names the server lists, by the bare name (see `_name`)
        self.landed = False  # a create or update was answered 200: the tiroir holds the text, whatever comes after
        self.wrote = False   # a create or update has been sent: from then on the tiroir may hold the text

    def _post(self, message: dict) -> tuple[int, dict | None, dict]:
        try:
            return self._post_checked(message)
        except Unreachable as e:
            if not self.wrote:
                raise
            cause = str(e).replace(" Nothing was sent.", "")
            raise SendError(f"{cause} Whether the write reached {self.origin} is not known: it may have reached it. Nothing "
                            "was changed on this laptop. Run sheaf again: a page that did arrive is taken up as this "
                            "file's, and a page of that name with other text is refused.") from None

    def _post_checked(self, message: dict) -> tuple[int, dict | None, dict]:
        status, got, back = post(self.origin + connect.DOOR_PATH, self.token, message, self.headers)
        if status == 403 and back.get("refusal"):       # the door says why: a token that was revoked says 401
            raise TokenRefused(f"{self.origin} answered 403: {back['refusal']}."
                               + ("" if self.landed else " Nothing was sent."))
        if status in (401, 403):
            raise TokenRefused(f"{self.origin} refused the token (it was revoked, or it is not a token of that address): "
                            "make a new one with Connect a laptop and run sheaf connect. Nothing was sent.")
        if status >= 500:
            raise Unreachable(f"{self.origin} answered with status {status}.")
        return status, got, back

    def _start(self):
        self.started = True
        status, got, back = self._post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "sheaf", "version": "send"}}})
        if status != 200 or not isinstance(got, dict) or not isinstance(got.get("result"), dict):
            raise SendError(f"the door of {self.origin} did not answer as an MCP door does (status {status}). "
                            "Nothing was sent.")
        if sid := back.get("mcp-session-id"):
            self.headers["Mcp-Session-Id"] = sid
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _name(self, name: str) -> str:
        """The name the server gives the tool `name`: the hub's own tools are bare (`create`), a door in front of the hub
        lists them under a prefix (`sheaf_create`). Read once from its `tools/list`, never assumed; a list that cannot
        be read leaves the bare name, which is what a server that has no such tool answers for."""
        if self.names is None:
            self.names = {}
            listed: set[str] = set()
            cursor = None
            for _ in range(5):                      # a door may page its list; five pages is far more than it has tools
                self.n += 1
                message = {"jsonrpc": "2.0", "id": self.n, "method": "tools/list"}
                if cursor:
                    message["params"] = {"cursor": cursor}
                try:
                    status, got, _ = self._post_checked(message)   # a refusal or an error here is the call's own to raise
                except SendError:
                    return name
                result = got.get("result") if isinstance(got, dict) else None
                tools = result.get("tools") if isinstance(result, dict) else None
                if status != 200 or not isinstance(tools, list):
                    break
                listed |= {t["name"] for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)}
                cursor = result.get("nextCursor")
                if not isinstance(cursor, str) or not cursor:
                    break
            # A door lists the hub's `create`, `update` and `read` under one prefix (`<prefix>create`...) and may list a tool of
            # its own that keeps a bare name, `read` among them: so the prefix is the one under which all three stand.
            prefixes = [n[:-len("create")] for n in listed if n.endswith("_create")
                        if {n[:-len("create")] + "update", n[:-len("create")] + "read"} <= listed]
            if len(prefixes) == 1:                  # every tool of the hub is then called under it, listed or not
                self.names = {bare: prefixes[0] + bare for bare in _HUB_TOOLS}
        return self.names.get(name, name)

    def tool(self, name: str, arguments: dict) -> tuple[bool, object]:
        """(is it an error, the parsed result or the sentence of the error) of one tool call."""
        if not self.started:
            self._start()
        sent = self._name(name)
        self.wrote = self.wrote or name in ("create", "update")
        self.n += 1
        status, got, _ = self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                                     "params": {"name": sent, "arguments": arguments}})
        self.landed = self.landed or (status == 200 and name in ("create", "update"))
        result = got.get("result") if isinstance(got, dict) else None
        content = result.get("content") if isinstance(result, dict) else None
        if status != 200 or not isinstance(content, list) or not content:
            raise SendError(f"the door of {self.origin} answered {name} with status {status} and no result. "
                            "Nothing was changed on this laptop.")
        text = content[0].get("text") if isinstance(content[0], dict) else None
        if not isinstance(text, str):
            raise SendError(f"the door of {self.origin} answered {name} with a result that holds no text.")
        if result.get("isError"):
            if (moved := _moved_part(text)) is not None:
                raise moved
            return True, text
        try:
            parsed = json.loads(text)
        except ValueError:
            raise SendError(f"the door of {self.origin} answered {name} with something that is not JSON.") from None
        for key in _RESULT_TEXT.get(name, ()):
            if not isinstance(parsed, dict) or not isinstance(parsed.get(key), str):
                raise SendError(f"the door of {self.origin} answered {name} with a result that has no `{key}`.")
        return False, parsed


@dataclasses.dataclass(frozen=True)
class Report:
    """The tiroir's answer to a render report once every hop of it is checked: what `report_page` reads, never the raw
    answer. `commit_known` is a bool for `ok` and None otherwise; `install` is the App's link for `no-app`; `moved_to` is
    the origin a `moved` root went to."""
    clone: str
    commit_known: bool | None = None
    install: str | None = None
    moved_to: str | None = None


_ANSWERS = (repos_mod.OK, repos_mod.NO_APP, repos_mod.NO_CLONES, repos_mod.PRIVATE_ROOT, repos_mod.CLONING,
            repos_mod.NOT_CLONED, repos_mod.MOVED)


def parse_report(origin: str, got: object) -> Report:
    """The typed report of the door's parsed answer, or SendError: an object whose `clone` is a value this CLI knows,
    with the fields that value needs and of the right type. The caller falls back to rendering on the laptop."""
    def bad(why: str):
        return SendError(f"the door of {origin} answered the render report with {why}.")

    if not isinstance(got, dict):
        raise bad("something that is no report")
    clone = got.get("clone")
    if not isinstance(clone, str) or clone not in _ANSWERS:
        raise bad("a clone state this sheaf does not know")
    known, install = got.get("commit_known"), got.get("install")
    if clone == repos_mod.OK and not isinstance(known, bool):
        raise bad("an ok without a commit_known yes or no")
    if install is not None and not isinstance(install, str):
        raise bad("an install link that is no text")
    moved_to = got.get("moved_to")
    if clone == repos_mod.MOVED and not (isinstance(moved_to, str) and moved_to and moved_to.isprintable()):
        raise bad("a moved without the origin it moved to")
    return Report(clone, known if clone == repos_mod.OK else None, install, moved_to if clone == repos_mod.MOVED else None)


def member_name(origin: str, token: str) -> str | None:
    """The name of the member the token acts for, for the second line. The door in front of the tiroir may not route
    this: then it is None and the line goes without it."""
    try:
        status, got, _ = get(origin + "/_/whoami", token)
    except SendError:
        return None
    name = got.get("name") if status == 200 and isinstance(got, dict) else None
    return name if isinstance(name, str) and name else None


# ── the state folder ─────────────────────────────────────────────────────────

def _state_path() -> Path:
    return paths.state_dir() / STATE_FILE


def read_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(data: dict):
    paths.private_dir(paths.state_dir())
    write_text_atomic(_state_path(), json.dumps(data, indent=1, sort_keys=True) + "\n", mode=0o600)


def row_of(md: Path, origin: str | None = None) -> dict | None:
    row = read_state().get(str(md.resolve()))
    ok = isinstance(row, dict) and all(isinstance(row.get(k), str) for k in ("tiroir", "doc", "hash", "local"))
    return row if ok and (origin is None or row["tiroir"] == origin) else None


def keep_row(md: Path, row: dict):
    with file_locked("sends.lock"):              # a read, a change and a write: two sheaf commands at once keep both rows
        data = read_state()
        data[str(md.resolve())] = row
        write_state(data)


# ── which tiroir, and with which credential ──────────────────────────────────

def tiroir_of(md: Path, warn) -> str | None:
    """The tiroir a page goes to: its root's `.sheaf.toml`, else the laptop's default; None when there is none or the
    page is inside a git directory."""
    folder = md.resolve().parent
    if config.git_place(folder).in_git_dir:
        return None
    named = config.load_root_config(folder, warn).tiroir or config.load_user_config(warn).tiroir
    return connect.origin_of(named) if named else None


def credential(origin: str) -> str | None:
    """The token this laptop holds for `origin`; None when it holds none or has no keyring to hold one."""
    try:
        return connect.token_for(origin)
    except connect.ConnectError:
        return None


# ── send and pull ────────────────────────────────────────────────────────────

def _beside(md: Path, n: int = 1) -> Path:
    return md.with_name(md.stem + (".tiroir" if n == 1 else f".tiroir-{n}") + md.suffix)


def _copy_for(md: Path, text: str) -> Path:
    """Where the tiroir's text goes beside `md`: `FILE.tiroir.md` when it is free or already holds exactly this text, else
    the next free `FILE.tiroir-2.md`, `-3`...; never over a file that is there (it may be a copy the person has begun to
    merge from, or a file of their own). Two commands at the very same instant can still choose one name."""
    n = 1
    while True:
        beside = _beside(md, n)
        if os.path.lexists(beside):
            try:
                if beside.is_file() and beside.read_text(encoding="utf-8") == text:
                    return beside
            except (OSError, UnicodeDecodeError):
                pass
            n += 1
            continue
        return beside


def _leave_theirs(md: Path, row: dict, now: dict, sending: bool = True) -> SendError:
    """The tiroir's text, written beside the file and recorded as read; the error that tells the agent what to do."""
    beside = _copy_for(md, now["text"])
    if not beside.exists():
        write_text_atomic(beside, now["text"])
    keep_row(md, {**row, "hash": now["hash"]})
    nothing = "so nothing was sent" if sending else "and the file has changes of yours"
    return SendError(f"{row['doc']} has changed on the shared Sheaf since you last read it, {nothing}. Its text is in "
                     f"{beside}: merge it into {md} and run sheaf {md} again.")


def _read_local(md: Path) -> str:
    try:
        return md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise SendError(f"{md} cannot be read as text ({e}).") from None


def _agent_label(environ) -> str:
    agent = detect(environ)
    return agent.product if agent and agent.product else "no agent"


def _shown(origin: str, member: str | None, doc: str, environ) -> list[str]:
    host = origin.split("://", 1)[1]
    who = f"as {member} · " if member else "as "
    return [origin + url_path(doc), f"on {host} {who}{_agent_label(environ)}", doc.rsplit("/", 1)[0]]


def _create(door: Door, md: Path, text: str, args, origin: str) -> dict:
    arguments = {"doc": md.name, "text": text}
    if args.folder is not None:
        arguments["folder"] = args.folder
    if args.keep:
        arguments["keep"] = True
    bad, got = door.tool("create", arguments)
    if bad and "exists already" in got and args.folder is None:
        arrived = _arrived(door, md, text, got.split(" exists already", 1)[0].strip(), origin)
        if arrived is not None:
            keep_row(md, {"tiroir": origin, "doc": arrived["doc"], "hash": arrived["hash"], "local": md_hash(text)})
            return arrived
    if bad and "exists already" in got:
        raise SendError(f"a page named {md.name} exists already on the shared Sheaf and was not sent from this file. "
                        f"Rename {md} and run sheaf again. Nothing was sent.")
    if bad:
        raise SendError(f"{got} Nothing was sent.")
    keep_row(md, {"tiroir": origin, "doc": got["doc"], "hash": got["hash"], "local": md_hash(text)})
    return got


def _arrived(door: Door, md: Path, text: str, address: str, origin: str) -> dict | None:
    """The page at `address` (the one the door's "exists already" named) when the tiroir holds exactly this file's text there: a
    create whose answer was lost took effect, and the run after it finds its own page. {doc, hash} of it, else None.
    None also when the state row of another local file that still exists holds that address: the page is that file's."""
    mine = str(md.resolve())
    if any(k != mine and Path(k).exists() and isinstance(r, dict) and r.get("tiroir") == origin and r.get("doc") == address
           for k, r in read_state().items()):
        return None
    try:
        bad, now = door.tool("read", {"doc": address})
    except (SendError, Moved):
        return None
    if bad or md_hash(now["text"]) != md_hash(text):
        return None
    return {"doc": address, "hash": now["hash"]}


def _update(door: Door, md: Path, text: str, row: dict) -> dict:
    bad, got = door.tool("update", {"doc": row["doc"], "text": text, "expected_hash": row["hash"]})
    if not bad:
        keep_row(md, {**row, "hash": got["hash"], "local": md_hash(text)})
        return got
    # Refused: when the tiroir's text is not the one this laptop last read, that is the reason, and its text is the answer.
    unread, now = door.tool("read", {"doc": row["doc"]})
    if not unread and now["hash"] != row["hash"]:
        raise _leave_theirs(md, row, now)
    raise SendError(f"{got} Nothing was sent.")


def _follow(md: Path, row: dict, moved: Moved, environ, say) -> tuple:
    """(the door of the tiroir the page went to, the page's row there, the token): the state row of `md` is rewritten to the new
    tiroir and the new address, and keeps this laptop's own last-read hash unless that was the text that moved: the update that follows
    goes the stale way when the page there is not what this laptop last read, whether it changed on the old tiroir before the move
    or on the new one after.
    A laptop with no credential for that tiroir is told the one line to run, and nothing is changed."""
    token = credential(moved.origin)
    if token is None:
        raise SendError(f"{moved} This laptop holds no credential for {moved.origin}: run `sheaf connect {moved.origin}` and "
                        f"run sheaf again. Nothing was sent and {md} is unchanged.")
    # the landed text is another hash than the text that left, so the row takes it only when this laptop last read the text that left
    read = moved.hash if moved.hash and moved.was and moved.was == row["hash"] else row["hash"]
    new = {**row, "tiroir": moved.origin, "doc": moved.address, "hash": read, "moved_from": row.get("moved_from", row["tiroir"])}
    keep_row(md, new)
    say(f"{row['doc']} was moved to {moved.origin.split('://', 1)[1]}: sent there")
    return Door(moved.origin, token, declared(environ)), new, token


# ── a page in a git repo: the render report ──────────────────────────────────

GITHUB_RE = re.compile(r"(?:https?://(?:[^/@]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)"
                       r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?")


def _git(top: Path, *args) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(top), "--literal-pathspecs", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def _git_probe(folder: Path) -> subprocess.CompletedProcess:
    """`git rev-parse` in `folder`, with git's messages in English; raises OSError or SubprocessError when git does not run."""
    return subprocess.run(["git", "-C", str(folder), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=10, env={**os.environ, "LC_ALL": "C"})


# git's own words for a folder under no repository; a broken repository says `not a git repository: <path>`, which is not this
NOT_A_REPO = re.compile(r"fatal: not a git repository \(or any (?:of the )?parent[^)]*\)")


def require_known_place(md: Path):
    """Return when git says the page's folder is inside a repository or plainly outside any: SendError for any other
    answer (git missing, a timeout, "dubious ownership", a repository git names as broken). The page is then not sent as a loose
    page, since a repository's page must never go up as one."""
    folder = md.resolve().parent
    try:
        done = _git_probe(folder)
    except (OSError, subprocess.SubprocessError) as e:
        raise SendError(f"cannot tell whether {md} is in a git repository: git did not run ({e}). Nothing was sent.") from None
    if done.returncode == 0:
        return
    why = (done.stderr or "").strip().splitlines()
    if why and NOT_A_REPO.match(why[0]) and not any("ownership" in l or "unsafe" in l for l in why):
        return
    raise SendError(f"cannot tell whether {md} is in a git repository: git said {why[0] if why else 'nothing'!r}. "
                    "Fix that (for dubious ownership: `git config --global --add safe.directory <folder>`) and run sheaf "
                    "again. Nothing was sent.")


class Local(Exception):
    """A repo page that cannot be reported: one sentence of why, and the page renders on the laptop hub."""


def _what_to_report(md: Path, top: Path, err) -> tuple[str, str, str]:
    """(repo `owner/name`, path in the repo, commit) of the page: the commit is the last that changed it, and it must
    be on the remote. Raises Local when there is nothing to report."""
    remote = _git(top, "config", "--get", "remote.origin.url")
    if remote.returncode != 0 or not remote.stdout.strip():
        raise Local(f"{md} is in a git repo with no remote, so the tiroir cannot clone it: rendering it on this laptop.")
    found = GITHUB_RE.fullmatch(remote.stdout.strip())
    if not found:
        raise Local(f"{md} is in a repo whose remote is not on GitHub, so the tiroir cannot clone it: rendering it "
                    "on this laptop.")
    path = md.resolve().relative_to(top).as_posix()
    last = _git(top, "log", "-1", "--format=%H", "--", path).stdout.strip()
    if not last:
        raise Local(f"{path} is not committed yet: commit and push it, then run sheaf again. Rendering it on this laptop.")
    if _git(top, "status", "--porcelain", "--", path).stdout.strip():
        err(f"sheaf: {path} has uncommitted changes: the tiroir shows the text of {last[:8]}, the last commit that "
            "changed it.")
    if not _git(top, "branch", "-r", "--contains", last).stdout.strip():
        raise Local(f"commit {last[:8]} of {path} is not on the remote yet: run git push, then sheaf again. Nothing "
                    "was sent; rendering it on this laptop.")
    return found.group(1), path, last


def report_page(md: Path, top: Path, origin: str, token: str, args, out, err, environ) -> int | None:
    """Tell the tiroir the page `md` of the repo at `top` is being worked on: a render report, never its text and
    never a push. None whenever the page renders here: the report could not be made, the tiroir could not take it, or it
    took it and the page still renders on this laptop (printing the report lines first) until it serves the clone."""
    if args.folder is not None or args.keep:
        err("sheaf: --folder and --keep go with a loose page; a page in a git repo stays in its repo")
        return 2
    try:
        repo, path, commit = _what_to_report(md, top, err)
    except Local as e:
        err(f"sheaf: {e}")
        return None
    door = Door(origin, token, declared(environ))
    try:
        bad, got = door.tool("render_report", {"repo": repo, "path": path, "commit": commit})
        report = None if bad else parse_report(origin, got)
    except Unreachable as e:
        err(f"sheaf: {e} The render report was dropped, not queued; rendering {md} on this laptop.")
        return None
    except TokenRefused:
        raise
    except SendError as e:          # a door with no render_report, a failed initialize, an answer that is no report
        err(f"sheaf: {e} The render report was dropped; rendering {md} on this laptop.")
        return None
    if bad:
        err(f"sheaf: the render report of {path} was refused: {got} Rendering {md} on this laptop.")
        return None
    clone = report.clone
    if clone == repos_mod.NO_APP:
        err(f"sheaf: the tiroir's GitHub App cannot reach {repo}, so it cannot clone it and {md} renders on this laptop "
            f"only. Add {repo} to the installation: {report.install or '(the tiroir gave no link)'}")
        return None
    if clone == repos_mod.NO_CLONES:
        err(f"sheaf: {origin} makes no repo clones, so {md} renders on this laptop.")
        return None
    if clone == repos_mod.PRIVATE_ROOT:
        err(f"sheaf: {repo} is your private root on {origin.split('://', 1)[-1]}, so the tiroir clones nothing and {md} "
            "renders on this laptop.")
        return None
    if clone == repos_mod.CLONING:
        err(f"sheaf: the tiroir is cloning {repo}; the next render goes there. {md} renders on this laptop this time.")
        return None
    if clone == repos_mod.MOVED:
        err(f"sheaf: {repo} moved to {report.moved_to.split('://', 1)[-1]}: pull the commit that set tiroir = "
            f"\"{report.moved_to}\" in its .sheaf.toml, then run sheaf again. {md} renders on this laptop.")
        return None
    if clone == repos_mod.NOT_CLONED:
        err(f"sheaf: {origin.split('://', 1)[-1]} has not cloned {repo}, so {md} renders on this laptop.")
        return None
    if report.commit_known is False:
        err(f"sheaf: the tiroir could not find commit {commit[:8]} on {repo}: is it pushed to GitHub? Rendering {md} "
            "on this laptop.")
        return None
    member = member_name(origin, token)
    host = origin.split("://", 1)[1]
    out(f"{repo} {path} @ {commit[:8]}")
    out(f"on {host} {'as ' + member + ' · ' if member else 'as '}{_agent_label(environ)}")
    return None         # the tiroir does not serve the clone yet: the page renders here as before, and prints its address


def send_page(md: Path, args, out, err, environ=None) -> int | None:
    """Send the page `md` and print where it is; None when nothing is to be sent and the caller renders here. A loose
    page goes through the door's `create` and `update`; a page in a git repo is a render report."""
    environ = os.environ if environ is None else environ
    if md.suffix != ".md" or not md.is_file():
        return None
    try:
        origin = tiroir_of(md, err)
        token = credential(origin) if origin else None
        if token is None:
            return None
        require_known_place(md)
        if (top := config.git_place(md.resolve().parent).top) is not None:
            return report_page(md, top, origin, token, args, out, err, environ)
        text = _read_local(md)
        row = row_of(md, origin)
        if row is None and (kept := row_of(md)) is not None and kept.get("moved_from") == origin:
            row = kept                  # the page went to another shared Sheaf: the file keeps following it there
            origin = row["tiroir"]
            if (token := credential(origin)) is None:
                raise SendError(f"this laptop holds no credential for {origin}, where {row['doc']} was moved: run "
                                f"`sheaf connect {origin}` and run sheaf again. Nothing was sent.")
        door = Door(origin, token, declared(environ))
        try:
            got = _update(door, md, text, row) if row else _create(door, md, text, args, origin)
        except Moved as moved:
            door, row, token = _follow(md, row, moved, environ, out)
            origin = moved.origin
            got = _update(door, md, text, row)
        member = member_name(origin, token)
    except Unreachable as e:
        err(f"sheaf: {e}")
        err(f"sheaf: not on {origin.split('://', 1)[1]}: run sheaf {md} again when it is back")
        return None
    except (SendError, connect.UsageError) as e:
        err(f"sheaf: {e}")
        return EXIT_FAILED
    for line in _shown(origin, member, got["doc"], environ):
        out(line)
    return EXIT_OK


def cmd_pull(argv: list[str], out=None, err=None) -> int:
    out = out or (lambda line="": print(line))
    err = err or (lambda line="": print(line, file=sys.stderr))
    p = argparse.ArgumentParser(prog="sheaf pull", usage="sheaf pull FILE.md",
                                description="Write the shared Sheaf's latest text of a page you sent into the file, "
                                            "unless you changed the file since: then it goes beside it as FILE.tiroir.md.")
    p.add_argument("file", metavar="FILE.md")
    md = Path(p.parse_args(argv).file)
    try:
        row = row_of(md)
        if row is None:
            raise SendError(f"{md} was never sent to a shared Sheaf from this laptop, so there is nothing to pull.")
        token = credential(row["tiroir"])
        if token is None:
            raise SendError(f"this laptop holds no credential for {row['tiroir']}: run sheaf connect.")
        local = _read_local(md)
        door = Door(row["tiroir"], token, declared())
        try:
            bad, now = door.tool("read", {"doc": row["doc"]})
        except Moved as moved:
            door, row, token = _follow(md, row, moved, os.environ, out)
            bad, now = door.tool("read", {"doc": row["doc"]})
        if bad:
            raise SendError(now)
        if md_hash(local) != row["local"]:
            if now["hash"] == row["hash"]:
                out(f"{md} has changes of yours and the shared Sheaf has nothing newer: nothing to pull.")
                return EXIT_OK
            raise _leave_theirs(md, row, now, sending=False)
        if now["hash"] == row["hash"]:
            out(f"{md} is the shared Sheaf's latest text already.")
            return EXIT_OK
        def check_unchanged():
            # An edit saved while the door was asked, or while the new text is written and synced, is the file's,
            # not the pull's: checked again just before the new text takes the file's place.
            if md_hash(_read_local(md)) != md_hash(local):
                raise _leave_theirs(md, row, now, sending=False)
        check_unchanged()
        write_text_atomic(md, now["text"], check=check_unchanged)
        keep_row(md, {**row, "hash": now["hash"], "local": md_hash(now["text"])})
        out(f"{md} now holds the shared Sheaf's latest text of {row['doc']}.")
        return EXIT_OK
    except (SendError, connect.UsageError) as e:
        err(f"sheaf: {e}")
        return EXIT_FAILED


COMMAND_HELP.update({"pull": ("pull FILE.md", "write the shared Sheaf's latest text of a page you sent into the file")})
