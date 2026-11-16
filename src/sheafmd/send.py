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

With `--local`, with no credential, or for a page in a git repo, nothing is sent: `send_page` answers None and the
caller renders on the laptop hub as before. The network is two functions, `post` and `get`, which a test replaces; the
keyring is `connect.system_store()`, which a test replaces too.
"""
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import config, connect, paths
from .agents.claude_code import config_dir_of
from .agents.detect import detect, session_id
from .atomic import write_text_atomic
from .hub.roots import url_path
from .hub.writelog import declared_link
from .source import md_hash

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
TIMEOUT = 15.0
STATE_FILE = "sends.json"
PROTOCOL = "2025-06-18"

COMMANDS: dict = {}
COMMAND_HELP: dict = {}


class SendError(Exception):
    """A send that stops: the message is one sentence a person reads, and says what was left unchanged."""


# ── the network: the two places a test stands in for the tiroir ─────────────

def _request(req) -> tuple[int, dict | None, dict]:
    try:
        with connect._NO_REDIRECT.open(req, timeout=TIMEOUT) as r:
            raw, status, headers = r.read(8 << 20), r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, None, {}
    except (urllib.error.URLError, OSError) as e:
        raise SendError(f"cannot reach {req.full_url.split('/', 3)[2]}: {getattr(e, 'reason', e)}. "
                        "Nothing was sent.") from None
    return status, connect._json_of(raw.decode("utf-8", "replace")) if raw.strip() else None, headers


def post(url: str, token: str, message: dict, headers: dict) -> tuple[int, dict | None, dict]:
    """(status, parsed JSON or None, response headers) of one JSON-RPC message sent to the door with the bearer."""
    req = urllib.request.Request(url, json.dumps(message).encode(), {
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream", **headers}, method="POST")
    return _request(req)


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


def declared(environ=None) -> dict:
    """The request headers a send declares itself with: session, machine, Remote Control link; only those it has."""
    environ = os.environ if environ is None else environ
    session = session_id(environ)
    out = {"X-Sheaf-Host": machine()}
    if session:
        out["X-Sheaf-Session"] = session
        if link := remote_link(environ, session):
            out["X-Sheaf-Link"] = link
    return {k: v for k, v in out.items() if v and v.isprintable() and len(v) <= 512}


# ── the door ─────────────────────────────────────────────────────────────────

class Door:
    """One tiroir's library door, with the token: `initialize` first (a door may keep a session), then each tool call."""

    def __init__(self, origin: str, token: str, headers: dict):
        self.origin, self.token, self.headers, self.n = origin, token, dict(headers), 0
        self.started = False

    def _post(self, message: dict) -> tuple[int, dict | None, dict]:
        status, got, back = post(self.origin + connect.DOOR_PATH, self.token, message, self.headers)
        if status in (401, 403):
            raise SendError(f"{self.origin} refused the token (it was revoked, or it is not a token of that address): "
                            "make a new one with Connect a laptop and run sheaf connect. Nothing was sent.")
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

    def tool(self, name: str, arguments: dict) -> tuple[bool, object]:
        """(is it an error, the parsed result or the sentence of the error) of one tool call."""
        if not self.started:
            self._start()
        self.n += 1
        status, got, _ = self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                                     "params": {"name": name, "arguments": arguments}})
        result = got.get("result") if isinstance(got, dict) else None
        if status != 200 or not isinstance(result, dict) or not result.get("content"):
            raise SendError(f"the door of {self.origin} answered {name} with status {status} and no result. "
                            "Nothing was changed on this laptop.")
        text = result["content"][0].get("text", "")
        if result.get("isError"):
            return True, text
        try:
            return False, json.loads(text)
        except ValueError:
            raise SendError(f"the door of {self.origin} answered {name} with something that is not JSON.") from None


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
    data = read_state()
    data[str(md.resolve())] = row
    write_state(data)


# ── which tiroir, and with which credential ──────────────────────────────────

def tiroir_of(md: Path, warn) -> str | None:
    """The tiroir a loose page goes to: its root's `.sheaf.toml`, else the laptop's default; None when there is none or
    the page is in a git repo (a repo page travels by git)."""
    folder = md.resolve().parent
    place = config.git_place(folder)
    if place.top is not None or place.in_git_dir:
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

def _beside(md: Path) -> Path:
    return md.with_name(md.stem + ".tiroir" + md.suffix)


def _leave_theirs(md: Path, row: dict, now: dict, door_says: str | None = None) -> SendError:
    """The tiroir's text, written beside the file and recorded as read; the error that tells the agent what to do."""
    beside = _beside(md)
    write_text_atomic(beside, now["text"])
    keep_row(md, {**row, "hash": now["hash"]})
    return SendError(f"{row['doc']} has changed on the shared Sheaf since you last read it, so nothing was sent. Its text is in "
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
    if bad:
        raise SendError(f"{got} Nothing was sent.")
    keep_row(md, {"tiroir": origin, "doc": got["doc"], "hash": got["hash"], "local": md_hash(text)})
    return got


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


def send_page(md: Path, args, out, err, environ=None) -> int | None:
    """Send the loose page `md` and print where it is; None when nothing is to be sent and the caller renders here."""
    environ = os.environ if environ is None else environ
    if md.suffix != ".md" or not md.is_file():
        return None
    try:
        origin = tiroir_of(md, err)
        token = credential(origin) if origin else None
        if token is None:
            return None
        text = _read_local(md)
        door = Door(origin, token, declared(environ))
        row = row_of(md, origin)
        got = _update(door, md, text, row) if row else _create(door, md, text, args, origin)
        member = member_name(origin, token)
    except (SendError, connect.UsageError) as e:
        err(f"sheaf: {e}")
        return EXIT_FAILED
    for line in _shown(origin, member, got["doc"], environ):
        out(line)
    return EXIT_OK


def cmd_pull(argv: list[str], out=None, err=None) -> int:
    import argparse
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
        bad, now = door.tool("read", {"doc": row["doc"]})
        if bad:
            raise SendError(f"{now}")
        if md_hash(local) != row["local"]:
            if now["hash"] == row["hash"]:
                out(f"{md} has changes of yours and the shared Sheaf has nothing newer: nothing to pull.")
                return EXIT_OK
            raise _leave_theirs(md, row, now)
        if now["hash"] == row["hash"]:
            out(f"{md} is the shared Sheaf's latest text already.")
            return EXIT_OK
        write_text_atomic(md, now["text"])
        keep_row(md, {**row, "hash": now["hash"], "local": md_hash(now["text"])})
        out(f"{md} now holds the shared Sheaf's latest text of {row['doc']}.")
        return EXIT_OK
    except (SendError, connect.UsageError) as e:
        err(f"sheaf: {e}")
        return EXIT_FAILED


COMMANDS.update({"pull": cmd_pull})
COMMAND_HELP.update({"pull": ("pull FILE.md", "write the shared Sheaf's latest text of a page you sent into the file")})
