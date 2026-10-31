"""
sheafmd.hub.proxy — proxy mode: the hub behind a front's sign-in, through a Unix socket (SPEC 9.9).

    load()                  the `[proxy]` table of config.toml, checked; None without one
    configured()            whether config.toml has a `[proxy]` table at all
    parse(table, where)     the same for a table already read (the tests build one)
    same_name(a, b)         whether two names would pass for each other once cleaned
    check_names(cfg, ...)   no member's name passes for anyone else's
    check_folder(cfg)       the proxy socket's folder is as the deployment must make it
    bind(cfg)               the proxy socket, listening; a stale one replaced
    unlink(cfg, made)       the proxy socket removed at a clean exit, if it is still the one made
    peer(conn)              the uid of the process at the other end of a connection
    member_lines()          the lines under Ask and Tell on a member's page (10.6)
    for_member(state)       a document's state as a member is told it: no thread told to the session

A `[proxy]` table in config.toml is the one switch (4.3): no flag, no environment variable. Every
key 9.9 names is required, and anything missing, unknown or wrong is a ProxyError, which stops the
hub's start with exit 1 and a `proxy-config` row: the hub never runs with part of the mode.
"""
import errno
import os
import pwd
import re
import socket
import stat
import struct
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .. import config, paths
from ..agents.detect import TABLE
from ..edit import MERGE_BY
from .auth import clean_display

TABLE_KEYS = {"origin": str, "socket": str, "proxy_user": str, "members": dict}
MEMBER_KEYS = {"name": str, "roots": list}
STREAM_SECONDS = 300            # a stream of the proxy socket is closed after this (9.9 "The credential")
# The only events a member's document stream is sent: the document's changes (an Ask's answer is
# one), the hub's stop, and `gone` when its root is forgotten, which names only the address the stream
# was opened on, a member's Tell that its fork's relay will not deliver (9.14), and what became of a drop for
# James's window: its supervisor's word on it (9.15), and its failure or no answer within the Tell wait (9.12), and
# `relay` when a fork's relay connects or is gone (9.14). Never a job of the hub account's agent session, nor
# `signed-out` (9.9).
DOCUMENT_EVENTS = ("hello", "changed", "ask-done", "hub-stopping", "gone", "tell-relay-failed", "box-failed",
                   "box-status", "relay")
PROXY_LINE = "Ask and Tell work only on the machine that runs the hub."     # 10.6
NO_DOCUMENTS = "This account has no documents on this hub."
FOLDER_MODE = 0o2750            # the socket's folder: the hub's account, the proxy's group, setgid
SOCKET_MODE = 0o660


def member_lines() -> dict:
    """What the page shows under its Ask and Tell buttons for a member (10.6)."""
    return {"ask": PROXY_LINE, "tell": PROXY_LINE}


def for_member(state: dict) -> dict:
    """A document's state (a snapshot, or the data of an event) as a member is told it: no thread
    told to the hub account's agent session (9.9). A snapshot holds nothing else of that session;
    `/_/doc` empties the rest itself."""
    return {**state, "telling": []} if "telling" in state else state


class ProxyError(Exception):
    """A `[proxy]` table the hub cannot start with. The message names the reason."""


@dataclass(frozen=True)
class Member:
    id: str                     # the front's id of the member: what `X-Sheaf-Member` carries
    name: str                   # signs their comments and replies, cleaned by the rule of 12
    roots: tuple                # the folders of their roots, absolute, as written
    email: str = ""             # the e-mail of their commits (8.11); "" for `default_email`
    short: str = ""             # their short name in `projects.toml` and in an action's `@name` (9.10)
    github: str = ""            # their GitHub login: the record's assignee who is them (9.10)
    shell: bool = False         # they have a shell on the box: the page offers them the attach command (9.12)
    tokens: tuple = ()          # the names of the door tokens that act for them (9.7, 9.11)


@dataclass(frozen=True)
class ProxyConfig:
    origin: str                 # https://host[:port], lower case: what every POST's Origin must be
    host: str                   # what every request's Host must be: origin's host, with its port
    socket: Path
    proxy_user: str
    uid: int                    # proxy_user's: the one uid the proxy socket serves
    gid: int                    # proxy_user's group: the group of the socket's folder
    members: dict               # id -> Member

    def member_of_token(self, name: str):
        """The member the door token `name` acts for, by their `tokens`; None for a token bound to nobody."""
        return next((m for m in self.members.values() if name in m.tokens), None)


def _read() -> dict:
    """The config file 4.1 names, read without printing a warning."""
    return config.read_toml(paths.config_file(), config.USER_KEYS, warn=lambda line: None)


def load() -> ProxyConfig | None:
    """The `[proxy]` table of the config file 4.1 names, checked; None when there is none."""
    try:
        data = _read()
    except config.ConfigError as e:
        raise ProxyError(str(e)) from None
    if "proxy" not in data:
        return None
    return parse(data["proxy"], paths.config_file())


def configured() -> bool:
    """Whether config.toml has a `[proxy]` table, whatever it holds: what a command that runs
    without the hub asks (`sheaf share`), so that a table the hub would refuse counts too. Raises
    config.ConfigError for a file that cannot be read."""
    return "proxy" in _read()


def _keys(t: dict, want: dict, where: str):
    """Every key of `want` there, of its type, and no other."""
    for key in t:
        if key not in want:
            raise ProxyError(f"unknown key '{key}' in {where}")
    for key, typ in want.items():
        if key not in t:
            raise ProxyError(f"'{key}' is missing from {where}")
        if not isinstance(t[key], typ):
            raise ProxyError(f"'{key}' must be {_WORDS[typ]}, not {t[key]!r}, in {where}")


_WORDS = {str: "text", list: "a list", dict: "a table"}
_HOST_RE = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]*[a-z0-9])?|\[[0-9a-f:.]+\]")
_EMAIL_RE = re.compile(r"[^\s<>@,;\"']+@[^\s<>@,;\"']+")
_SHORT_RE = re.compile(r"[A-Za-z0-9._-]{1,40}")
_LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
OPTIONAL_MEMBER_KEYS = ("email", "short", "github", "shell", "tokens")
_OPTIONAL_WORDS = {"short": "1 to 40 letters, digits, dots, dashes or underscores (nell)",
                   "github": "a GitHub login (tiroir)"}
SOCKET_MAX = 107                # bytes of a Unix socket's path (sun_path less its NUL)


def _origin(origin: str, where: str) -> tuple[str, str]:
    """(origin, host) as every request must name them: `https://`, a host, a port at most."""
    wrong = ProxyError(f"'origin' in {where} must be https://, a host and a port at most "
                       f"(https://chat.example.com), not {origin!r}")
    try:
        u = urlsplit(origin)
        port = u.port
    except ValueError:
        raise wrong from None
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.path or u.query or u.fragment or origin.endswith(("?", "#")) \
            or u.username is not None or not host or port == 0:
        raise wrong
    if ":" in host:
        host = f"[{host}]"
    if not _HOST_RE.fullmatch(host):
        raise wrong
    netloc = host if port in (None, 443) else f"{host}:{port}"      # a browser names 443 by no port
    return "https://" + netloc, netloc


def parse(t: dict, where) -> ProxyConfig:
    """The table `t` (read from `where`), checked as 9.9 says. Raises ProxyError."""
    here = f"[proxy] of {where}"
    if not t.get("members") and all(k in TABLE_KEYS for k in t):
        _keys({**t, "members": {}}, TABLE_KEYS, here)          # a missing key is said first
        raise ProxyError(f"{here} has no member: add a [proxy.members.\"<id>\"] with name and roots")
    _keys(t, TABLE_KEYS, here)
    origin, host = _origin(t["origin"], here)
    sock = t["socket"]
    if not sock.startswith("/"):
        raise ProxyError(f"'socket' must be an absolute path, in {here}: {sock!r}")
    if len(os.fsencode(sock)) > SOCKET_MAX:
        raise ProxyError(f"'socket' is longer than the {SOCKET_MAX} bytes a Unix socket's path may be, in {here}")
    try:
        acct = pwd.getpwnam(t["proxy_user"])
    except KeyError:
        raise ProxyError(f"'proxy_user' names no account of this machine: "
                         f"{t['proxy_user']!r}, in {here}") from None
    members = {}
    for mid, m in t["members"].items():
        mhere = f'[proxy.members."{mid}"] of {where}'
        if not isinstance(m, dict):
            raise ProxyError(f"{mhere} must be a table with name and roots")
        email = m.get("email", None)
        if email is not None and (not isinstance(email, str) or not _EMAIL_RE.fullmatch(email)):
            raise ProxyError(f"'email' must be an address like name@example.com, not {email!r}, in {mhere}")
        for key, rule in (("short", _SHORT_RE), ("github", _LOGIN_RE)):
            v = m.get(key)
            if v is not None and (not isinstance(v, str) or not rule.fullmatch(v)):
                raise ProxyError(f"'{key}' must be {_OPTIONAL_WORDS[key]}, not {v!r}, in {mhere}")
        if not isinstance(m.get("shell", False), bool):
            raise ProxyError(f"'shell' must be true or false, not {m['shell']!r}, in {mhere}")
        tokens = m.get("tokens", [])
        if not isinstance(tokens, list) or not all(isinstance(t, str) and _SHORT_RE.fullmatch(t) for t in tokens):
            raise ProxyError(f"'tokens' must be a list of token names, each 1 to 40 letters, digits, dots, "
                             f"dashes or underscores, not {tokens!r}, in {mhere}")
        _keys({k: v for k, v in m.items() if k not in OPTIONAL_MEMBER_KEYS}, MEMBER_KEYS, mhere)
        name = clean_display(m["name"])
        if not name:
            raise ProxyError(f"'name' has no printable character, in {mhere}")
        if not m["roots"]:
            raise ProxyError(f"'roots' must name at least one folder, in {mhere}")
        roots = []
        for r in m["roots"]:
            if not isinstance(r, str) or not r.startswith("/"):
                raise ProxyError(f"every folder of 'roots' must be an absolute path, not {r!r}, in {mhere}")
            roots.append(r.rstrip("/") or "/")
        members[mid] = Member(mid, name, tuple(roots), email or "", m.get("short", ""), m.get("github", ""),
                              m.get("shell", False), tuple(tokens))
        for name_ in tokens:
            if any(name_ in o.tokens for o in members.values() if o.id != mid):
                raise ProxyError(f"token {name_!r} of {mhere} acts for another member already")
        for key in ("short", "github"):
            mine = getattr(members[mid], key).casefold()
            if mine and any(getattr(o, key).casefold() == mine for o in members.values() if o.id != mid):
                raise ProxyError(f"'{key}' {getattr(members[mid], key)!r} of {mhere} is another member's")
    return ProxyConfig(origin, host, Path(sock), t["proxy_user"], acct.pw_uid, acct.pw_gid, members)


def default_email(mid: str, origin: str) -> str:
    """The e-mail of a member's commits whose block names none (8.11): their id at the front's host."""
    local = mid if re.fullmatch(r"[A-Za-z0-9._+-]+", mid) else "member"
    return f"{local}@{urlsplit(origin).hostname}"


def commit_email(member: Member, origin: str) -> str:
    """The e-mail of `member`'s commits (8.11): their block's, else `default_email`."""
    return member.email or default_email(member.id, origin)


def same_name(a: str, b: str) -> bool:
    """Two names a reader would take for one: the same once cleaned, whatever their case."""
    return clean_display(a).casefold() == clean_display(b).casefold()


def check_names(cfg: ProxyConfig, person: str, tokens) -> None:
    """A comment's name is the only record of its author in the file (5.2), so a member's name
    must not pass for anyone else's: another member's, the hub's person's (4.3), an agent's of
    11.5, an MCP token's display name (9.7), or `sheaf`, which signs the notes of a merge; and it
    must not end in `(action)`, which 5.3 reads as a role. Raises ProxyError."""
    seen = []
    for m in cfg.members.values():
        here = f'[proxy.members."{m.id}"]'
        if any(same_name(m.name, other) for other in seen):
            raise ProxyError(f"the name {m.name!r} of {here} is another member's")
        seen.append(m.name)
        if same_name(m.name, person):
            raise ProxyError(f"the name {m.name!r} of {here} is the hub's person's (config.toml name)")
        if any(same_name(m.name, a.display) for a in TABLE):
            raise ProxyError(f"the name {m.name!r} of {here} is an agent's (11.5)")
        if any(same_name(m.name, t) for t in tokens):
            raise ProxyError(f"the name {m.name!r} of {here} is an MCP token's display name (sheaf token list)")
        if same_name(m.name, MERGE_BY):
            raise ProxyError(f"the name {m.name!r} of {here} is sheaf's own, which signs the notes of a merge")
        if m.name.casefold().endswith("(action)"):
            raise ProxyError(f"the name {m.name!r} of {here} ends in (action), which a reply reads as its role")


# ── the proxy socket (9.9 "Two listeners") ───────────────────────────────────

def check_folder(cfg: ProxyConfig) -> None:
    """The socket's folder is the deployment's, made by root: owned by the hub's account and by
    proxy_user's group, mode 2750, so that the socket made in it belongs to that group and no
    other account can open it. The hub checks it and changes nothing. Raises ProxyError."""
    folder = cfg.socket.parent
    try:
        st = os.lstat(folder)
    except FileNotFoundError:
        raise ProxyError(f"the folder of the proxy socket, {folder}, does not exist: the deployment "
                         f"makes it, owned by this account and {cfg.proxy_user}'s group, mode 2750") from None
    except OSError as e:
        raise ProxyError(f"the folder of the proxy socket, {folder}, cannot be looked at "
                         f"({e.strerror or type(e).__name__})") from None
    if not stat.S_ISDIR(st.st_mode):
        raise ProxyError(f"the folder of the proxy socket, {folder}, is not a folder (a link is not one)")
    if st.st_uid != os.getuid():
        raise ProxyError(f"the folder of the proxy socket, {folder}, belongs to uid {st.st_uid}, "
                         f"not to this account (uid {os.getuid()})")
    if st.st_gid != cfg.gid:
        raise ProxyError(f"the folder of the proxy socket, {folder}, has group {st.st_gid}, "
                         f"not {cfg.proxy_user}'s ({cfg.gid})")
    if stat.S_IMODE(st.st_mode) != FOLDER_MODE:
        raise ProxyError(f"the folder of the proxy socket, {folder}, has mode "
                         f"{stat.S_IMODE(st.st_mode):o}, not 2750")


def bind(cfg: ProxyConfig) -> tuple[socket.socket, tuple]:
    """The proxy socket, listening, mode 0660, and the (device, inode) of its file, by which the
    hub knows at its exit that the file is still its own. A socket file that nothing listens on
    (an unclean exit left it) is replaced; one that something answers on, and anything that is
    not a socket, is a ProxyError and is left as it is."""
    path = str(cfg.socket)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise ProxyError(f"the proxy socket {path} cannot be looked at ({e.strerror or type(e).__name__})") from None
    else:
        if not stat.S_ISSOCK(st.st_mode):
            raise ProxyError(f"{path} exists and is not a socket: the hub does not remove it")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(2)
        try:
            probe.connect(path)
        except ConnectionRefusedError:
            os.unlink(path)                                  # stale: nothing listens on it
        except OSError as e:
            raise ProxyError(f"the hub cannot tell whether something listens on the proxy socket "
                             f"{path} ({e.strerror or type(e).__name__})") from None
        else:
            raise ProxyError(f"something listens on the proxy socket {path} already")
        finally:
            probe.close()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.bind(path)
        os.chmod(path, SOCKET_MODE)
        s.listen(64)
        st = os.lstat(path)
    except OSError as e:
        s.close()
        if e.errno == errno.EADDRINUSE:
            raise ProxyError(f"something listens on the proxy socket {path} already") from None
        raise ProxyError(f"the proxy socket {path} cannot be made ({e.strerror or type(e).__name__})") from None
    return s, (st.st_dev, st.st_ino)


def unlink(cfg: ProxyConfig, made: tuple) -> None:
    """Remove the proxy socket at a clean exit, if its file is still the one `bind` made."""
    try:
        st = os.lstat(cfg.socket)
        if (st.st_dev, st.st_ino) == made:
            os.unlink(cfg.socket)
    except OSError:
        pass


@dataclass(frozen=True)
class Peer:
    """Who is at the other end of a connection to the proxy socket, as the kernel says."""
    uid: int


SOL_LOCAL = 0                                                # <sys/un.h>: the level of LOCAL_PEERCRED
XUCRED, XUCRED_VERSION = "@IIh16I", 0                                           # struct xucred: version, uid, ngroups, groups


def peer(conn: socket.socket) -> Peer:
    """The uid of the process that connected, read from the connection: `SO_PEERCRED` on Linux,
    `LOCAL_PEERCRED` on macOS, which has no `SO_PEERCRED`."""
    if hasattr(socket, "SO_PEERCRED"):
        fmt = "3i"                                           # struct ucred: pid, uid, gid
        _, uid, _ = struct.unpack(fmt, conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                       struct.calcsize(fmt)))
        return Peer(uid)
    raw = conn.getsockopt(SOL_LOCAL, socket.LOCAL_PEERCRED, struct.calcsize(XUCRED))
    version, uid = struct.unpack_from("=II", raw)
    if version != XUCRED_VERSION:
        raise OSError(f"struct xucred of version {version}, not {XUCRED_VERSION}")
    return Peer(uid)
