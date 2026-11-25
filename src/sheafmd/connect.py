"""
sheafmd.connect — `sheaf connect <tiroir-url> <token>` (SPEC 9.7, 13).

"Connect a laptop" in the Sheaf makes a token for one laptop and one member and shows this one line. Running it:

    1. asks the tiroir's door whether the token opens it (any door version is accepted: what it answers to
       `initialize` is read, never compared with a version this CLI knows),
    2. keeps the token in the login keyring, under the tiroir's address,
    3. adds the tiroir's door to Claude Code's MCP entries with the token as its Authorization header,
    4. writes the tiroir as the laptop's default in config.toml when the laptop has none.

Nothing is written unless the door accepted the token, and the token is never printed. Where the files are comes from
the home folder at the time of the call, so a test that sets HOME is honoured. The keyring is `system_store()`, which a
test replaces.
"""
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, paths
from .atomic import write_text_atomic
from .hub.auth import TOKEN_PREFIX

SERVICE = "sheaf"
PEER_SERVICE = "sheaf-peer"     # the token this tiroir sends to a peer tiroir's channel (ticket 20): another entry than a laptop's
DOOR_PATH = "/mcp"                  # the tiroir's library door, under its front address
HEADERS_HELPER = "sheaf headers"    # the entry's headersHelper: names the session on a door write, holds no token (tells_poll.cmd_headers)
TIMEOUT = 8.0
_TOKEN = re.compile(re.escape(TOKEN_PREFIX) + r"[A-Za-z0-9_-]{43}")


class ConnectError(Exception):
    """Something that stops `sheaf connect`: the message says what and what was left unwritten."""


class UsageError(ConnectError):
    """The command line is wrong: exit 2."""


# ── the keyring ──────────────────────────────────────────────────────────────

class SystemStore:
    """The login keyring through the `keyring` package: the Secret Service on Linux, the Keychain on macOS."""

    def __init__(self):
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError:
            raise ConnectError("the `keyring` package is not installed") from None
        self._k, self._error = keyring, KeyringError
        backend = keyring.get_keyring()
        if getattr(backend, "priority", 1) < 1 or type(backend).__module__.startswith("keyring.backends.fail"):
            raise ConnectError("no login keyring on this computer (on Linux, install and unlock GNOME Keyring or KWallet)")

    def get(self, service: str, user: str):
        try:
            return self._k.get_password(service, user)
        except self._error as e:
            raise ConnectError(f"the login keyring could not be read: {e}") from None

    def set(self, service: str, user: str, secret: str):
        try:
            self._k.set_password(service, user, secret)
        except self._error as e:
            raise ConnectError(f"the login keyring did not take the token: {e}") from None


def system_store():
    return SystemStore()


_WARNED: set[str] = set()      # the credential files already warned about, by name


def peer_credential_name(url: str) -> str:
    """The name of the file that holds the token for the peer tiroir at `url`, in a service's credentials folder (systemd
    `LoadCredential=NAME:PATH` makes it `$CREDENTIALS_DIRECTORY/NAME`): one safe word per origin and port, `sheaf-peer-<host>`
    then `_p<port>` when the origin names one. No two origins share it, or the token kept for one peer would be sent to the
    other (ticket 190): a character of the host outside `[a-z0-9.-]` is written `_` and two hex digits for each of its bytes."""
    parts = urllib.parse.urlsplit(origin_of(url))
    host = parts.netloc[:-len(f":{parts.port}")] if parts.port else parts.netloc
    word = "".join(c if re.fullmatch(r"[a-z0-9.-]", c) else "".join(f"_{b:02x}" for b in c.encode()) for c in host)
    return "sheaf-peer-" + word + (f"_p{parts.port}" if parts.port else "")


def _credential_file(url: str) -> str | None:
    """The token in this service's credentials folder for the peer at `url`, or None: no folder, no file, or a file that is
    no token (the keyring is then asked, as before)."""
    folder = os.environ.get("CREDENTIALS_DIRECTORY")
    if not folder:
        return None
    name = peer_credential_name(url)
    try:
        text = (Path(folder) / name).read_text()
    except OSError:
        _said_old_name(folder, url, name)
        return None
    except UnicodeDecodeError:       # a corrupted file is a missing one; the warning names the file, never what is in it
        if name not in _WARNED:      # said once per process: the hub asks on every send
            _WARNED.add(name)
            print(f"sheaf: the credential file {name} is not text, so it is ignored and the keyring is asked", file=sys.stderr)
        return None
    token = text.strip()
    return token if _TOKEN.fullmatch(token) else None


def _said_old_name(folder: str, url: str, name: str):
    """A file left under the name a port had before ticket 190 (`sheaf-peer-<host>-<port>`) is never read, since that name was
    also another host's: say once which file to write again, and nothing of what is in it."""
    port = urllib.parse.urlsplit(origin_of(url)).port
    if not port:
        return
    old = name[:-len(f"_p{port}")] + f"-{port}"
    if old not in _WARNED and (Path(folder) / old).is_file():
        _WARNED.add(old)
        print(f"sheaf: the credential file {old} has the name of before, which is not read; keep the token again with "
              f"`sheaf peer use --store file`, as {name}", file=sys.stderr)


def peer_token_for(url: str, store=None) -> str | None:
    """The token this tiroir holds for the peer tiroir at `url` (`sheaf peer use`), or None. A service's credentials folder
    (`$CREDENTIALS_DIRECTORY`, the file store) is read first; only then the keyring, which a server may not have."""
    return _credential_file(url) or (store or system_store()).get(PEER_SERVICE, origin_of(url))


def use_peer(url: str, token: str, store=None) -> str:
    """Keep `token` as the one this tiroir sends to the peer at `url`: in the login keyring, nowhere else. Returns the origin."""
    origin = origin_of(url)
    _check_peer_token(token)
    (store or system_store()).set(PEER_SERVICE, origin, token)
    return origin


def use_peer_file(url: str, token: str, folder: Path) -> Path:
    """Keep `token` in the file store instead: one 0600 file named by `peer_credential_name` in `folder` (made 0700 if it is
    not there), for a service to load as a credential. An earlier file for the same peer is replaced whole. Returns the path."""
    origin = origin_of(url)
    _check_peer_token(token)
    folder = Path(folder)
    target = folder / peer_credential_name(origin)
    tmp = folder / (target.name + ".new")
    made = False                     # the temp is ours to remove only once we made it: a leftover link is left as it was
    try:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        made = True
        try:
            os.fchmod(fd, 0o600)
            data = memoryview((token + "\n").encode("ascii"))
            while data:
                data = data[os.write(fd, data):]
            os.fsync(fd)
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass                 # what failed first is what is told, not the close that follows it
            raise
        os.close(fd)
        os.replace(tmp, target)
    except OSError as e:
        if made:
            _drop(tmp)
        raise ConnectError(f"cannot keep the token in {folder}: {e.strerror or e}; nothing was written") from None
    except BaseException:
        if made:
            _drop(tmp)
        raise
    return target


def _drop(tmp: Path) -> None:
    """Remove a temp left by a failed write; a cleanup that fails too is not told: what failed first is."""
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


def _check_peer_token(token: str) -> None:
    if not _TOKEN.fullmatch(token or ""):
        raise UsageError("that is not a Sheaf token: copy the whole token that `sheaf peer add` printed on the other shared Sheaf")


def token_for(url: str, store=None) -> str | None:
    """The token this laptop holds for the tiroir at `url`, or None. What `sheaf FILE.md` will send."""
    return (store or system_store()).get(SERVICE, origin_of(url))


# ── the tiroir's address and its door ────────────────────────────────────────

def origin_of(url: str) -> str:
    """`https://host[:port]` of a tiroir's address, lower case; UsageError for anything else."""
    parts = urllib.parse.urlsplit(url.strip())
    ok = (parts.scheme == "https" and parts.hostname and not parts.username and not parts.password
          and parts.path in ("", "/") and not parts.query and not parts.fragment)
    if not ok:
        raise UsageError(f"{url!r} is not the address of a shared Sheaf: write it as https://host, with no path")
    try:
        port = parts.port
    except ValueError:
        raise UsageError(f"{url!r} has a port that is not a number from 0 to 65535") from None
    if port == 0:
        raise UsageError(f"{url!r} has port 0, which no Sheaf listens on")
    host = parts.hostname.lower()
    if ":" in host:                  # an IPv6 address: urlsplit drops its brackets, an address needs them
        host = f"[{host}]"
    return f"https://{host}" + (f":{port}" if port else "")


def entry_name(origin: str) -> str:
    return "sheaf-" + re.sub(r"[\[\]]", "", urllib.parse.urlsplit(origin).netloc).replace(":", "-")


class _Refuse3xx(urllib.request.HTTPRedirectHandler):
    """A redirect is an answer, never followed: the bearer would go with it to whatever host it names."""
    def redirect_request(self, *args, **kwargs):
        return None


_NO_REDIRECT = urllib.request.build_opener(_Refuse3xx)


def probe(url: str, token: str):
    """(status, parsed JSON or None) of the door's answer to `initialize`, sent with the token. Any 2xx body is
    parsed; a refusal is its status. The one place `connect` touches the network."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "sheaf", "version": "connect"}}}).encode()
    req = urllib.request.Request(url, body, {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                             "Accept": "application/json, text/event-stream"}, method="POST")
    try:
        with _NO_REDIRECT.open(req, timeout=TIMEOUT) as r:
            raw, status = r.read(1 << 20), r.status
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError) as e:
        raise ConnectError(f"cannot reach {url}: {getattr(e, 'reason', e)}") from None
    return status, _json_of(raw.decode("utf-8", "replace"))


def _json_of(text: str):
    """A JSON body, or the first `data:` line of an event stream (a door may answer either)."""
    try:
        return json.loads(text)
    except ValueError:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:])
                except ValueError:
                    return None
    return None


def check_door(origin: str, token: str) -> None:
    status, got = probe(origin + DOOR_PATH, token)
    if status in (401, 403):
        raise ConnectError(f"{origin} refused the token (it was revoked, or it is not a token of that address): "
                           "make a new one with Connect a laptop. Nothing was written.")
    if status != 200 or not isinstance(got, dict) or not isinstance(got.get("result"), dict):
        raise ConnectError(f"the door of {origin} did not answer as an MCP door does (status {status}). Nothing was written.")


# ── what is written ──────────────────────────────────────────────────────────

def claude_json() -> Path:
    """Claude Code's user file: `.claude.json` in CLAUDE_CONFIG_DIR when it is set, else in the home folder."""
    d = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return (Path(d) if d else Path.home()) / ".claude.json"


def add_mcp_entry(origin: str, token: str) -> Path:
    """The tiroir's door among Claude Code's MCP servers, as an HTTP server with the token in its header. Only this
    tiroir's own entry is made or replaced; every other key of the file is kept as it is."""
    path = claude_json()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError) as e:
        raise ConnectError(f"{path} cannot be read as JSON ({e}): the token is kept in the keyring only, "
                           "and nothing else was written.") from None
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise ConnectError(f"{path} is not a Claude Code settings file: nothing was written there.")
    data.setdefault("mcpServers", {})[entry_name(origin)] = {
        "type": "http", "url": origin + DOOR_PATH, "headers": {"Authorization": f"Bearer {token}"},
        "headersHelper": HEADERS_HELPER}
    write_text_atomic(path, json.dumps(data, indent=2) + "\n", mode=0o600)   # it holds a token: owner only
    return path


def _with_default(origin: str) -> str | None:
    """config.toml's text with `tiroir = "<origin>"` in it, or None when the laptop already has a default. The rest of
    the file is kept byte for byte; the line goes before the first table, where a top-level key belongs. A key left
    empty is filled where it stands. ConnectError when the result would not read with the default in it (a form of
    empty key this does not know): nothing is then written."""
    path = paths.config_file()
    if config.read_toml(path, config.USER_KEYS, warn=lambda line: None).get("tiroir"):
        return None
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"tiroir = {json.dumps(origin)}\n"
    table = re.search(r"^\s*\[", text, re.M)
    at = table.start() if table else len(text)
    head = text[:at]
    empty = re.search(r"^[ \t]*[\"\']?tiroir[\"\']?[ \t]*=[ \t]*(\"\"\"\"\"\"|\'\'\'\'\'\'|\"\"|\'\')[ \t\r]*(#[^\n]*)?$\n?", head, re.M)
    if empty:                        # a default that was left empty: fill its line, a second key would not parse
        out = head[:empty.start()] + line + head[empty.end():] + text[at:]
    else:
        glue = "" if not head or head.endswith("\n") else "\n"
        out = head + glue + line + ("\n" if table and head.strip() else "") + text[at:]
    try:
        ok = tomllib.loads(out).get("tiroir") == origin
    except tomllib.TOMLDecodeError:
        ok = False
    if not ok:
        raise ConnectError(f"{path} has a `tiroir` entry that sheaf cannot fill in: set it to {origin!r} by hand "
                           "or remove it, and run the command again. Nothing was written.")
    return out


def make_default(origin: str) -> bool:
    """Write `tiroir = "<origin>"` into config.toml when the laptop has no default tiroir; whether it did."""
    out = _with_default(origin)
    if out is None:
        return False
    write_text_atomic(paths.config_file(), out)
    return True


def check_config(origin: str) -> None:
    """The laptop's config.toml reads and can take the default, before the token is stored: a file `make_default`
    cannot write would stop the command after the token was already written."""
    try:
        out = _with_default(origin)
    except config.ConfigError as e:
        raise ConnectError(f"{e}. Mend that file and run the command again. Nothing was written.") from None
    if out is not None:
        folder = paths.config_file().parent
        while not folder.exists() and folder != folder.parent:
            folder = folder.parent
        if not folder.is_dir() or not os.access(folder, os.W_OK | os.X_OK):
            raise ConnectError(f"{paths.config_file()} cannot be written: {folder} is not a folder this laptop can write "
                               "into. Make it writable and run the command again. Nothing was written.")


def connect(url: str, token: str, out=print) -> None:
    """The four steps, in order; the first that fails stops the rest and says what was left unwritten."""
    origin = origin_of(url)
    if not _TOKEN.fullmatch(token or ""):
        raise UsageError("that is not a Sheaf token: copy the whole `sheaf connect` line from Connect a laptop")
    check_door(origin, token)
    check_config(origin)
    store = system_store()
    store.set(SERVICE, origin, token)
    entry = add_mcp_entry(origin, token)
    first = make_default(origin)
    out(f"Connected to {origin}. The token is in your login keyring and the door is in {entry}.")
    out(f"{origin} is now this laptop's default." if first else "Your default address is unchanged.")
