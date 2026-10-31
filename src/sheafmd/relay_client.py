"""
sheafmd.relay_client — `sheaf relay`: the member's side of the relay of a forked session (SPEC 9.14, sheaf#117).

    sheaf relay --hub ORIGIN --doc ADDRESS --session ID --token-file FILE [--config-dir DIR]
    sheaf relay revoke ADDRESS

Run on the member's machine beside the fork. It holds `GET /_/relay` open through the front, outbound only, and
hands each Tell to the session as the hub's own Tell would be (11.4): a peer message in the envelope, by the
session's adapter, with the Tell's id as `msg_id`, so a Tell sent again after a reconnect is the same message.
Then it acks it. The token is read from a 0600 file of this user's, never from argv, and is never printed.
`revoke`, run as the hub's account on the hub's machine, ends every relay token of a sheaf.
Registered in COMMANDS and COMMAND_HELP, which the foot of cli.py merges into its own.
"""
import argparse
import json
import os
import re
import shutil
import socket
import stat
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote

from . import paths
from .agents import registry
from .agents.base import DeliveryError, Target
from .agents.claude_code import config_dir_of
from .hub.jobs import Job

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
TOKEN_RE = re.compile(r"sheaf_relay_[A-Za-z0-9_-]{43}")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
BACKOFF = (1, 2, 5, 10, 30, 60)         # seconds between tries after a stream that failed, the last repeated
CLEARED = "no open session {id}: if it was cleared (/clear), fork again"
AGENT = "claude-code"

COMMANDS: dict = {}
COMMAND_HELP: dict = {}


class Refused(Exception):
    """The relay cannot go on; the message is one sentence a person reads."""


class Gone(Exception):
    """The hub says the token is no good, or the fork is no longer the sheaf's live session."""


def _err(line: str = ""):
    print(line, file=sys.stderr)


def read_token(path: str) -> str:
    """The token of `path`: a regular file of this user's, reached without a link, that no one else may read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as e:
        raise Refused(f"cannot open the token file {path} ({e.strerror or e}); a link is not followed") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused(f"the token file {path} is not a regular file")
        if st.st_uid != os.getuid():
            raise Refused(f"the token file {path} is not yours")
        if stat.S_IMODE(st.st_mode) & 0o077:
            raise Refused(f"the token file {path} may be read by others: chmod 600 it")
        text = os.read(fd, 4096).decode("ascii", "replace").strip()
    finally:
        os.close(fd)
    if not TOKEN_RE.fullmatch(text):
        raise Refused(f"the token file {path} holds no relay token")
    return text


def events(lines):
    """(name, data) of each event of an event stream, read from its lines (bytes, with or without the end)."""
    name, data = "message", []
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if not line:
            if data:
                yield name, "\n".join(data)
            name, data = "message", []
        elif line.startswith(":"):
            continue
        else:
            field, _, value = line.partition(":")
            value = value.removeprefix(" ")
            if field == "event":
                name = value
            elif field == "data":
                data.append(value)


class Sender:
    """The relay's own socket under the runtime folder, named as the envelope's sender: what reaches it is logged
    and nothing more, since the relay answers nothing a session says."""

    def __init__(self):
        self.path = paths.private_dir(paths.runtime_dir()) / f"sheaf-relay-{os.getpid()}.sock"
        self.path.unlink(missing_ok=True)
        self._s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._s.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self._s.listen(4)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._s.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                try:
                    got = conn.recv(4096)
                except OSError:
                    continue
            if got:
                _err(f"sheaf relay: a session wrote to this relay; nothing answers here ({len(got)} bytes)")

    def close(self):
        self._s.close()
        self.path.unlink(missing_ok=True)


class Relay:
    """One relay: `run()` holds the stream and delivers until the hub says `gone`. `opener` and `deliver` are the
    network and the session, which a test replaces."""

    def __init__(self, hub: str, doc: str, session: str, token: str, config_dir: str, opener=None, deliver=None,
                 sleep=time.sleep):
        self.hub, self.doc, self.session, self._token = hub.rstrip("/"), doc, session, token
        self.config_dir = config_dir
        self._open = opener or urllib.request.urlopen
        self._deliver = deliver or self._to_session
        self._sleep = sleep
        self.sender = None

    def _request(self, url: str, data: bytes | None = None, **headers) -> urllib.request.Request:
        """A request to the front. The token is an unredirected header: urllib copies the others onto a
        redirect, which could carry the token to another host."""
        req = urllib.request.Request(url, data, method="POST" if data is not None else "GET",
                                     headers={"Origin": self.hub, **headers})
        req.add_unredirected_header("Authorization", f"Bearer {self._token}")
        return req

    def _to_session(self, message: str, msg_id: str):
        ad = registry.adapter_for(AGENT, f"uds:{self.sender.path}" if self.sender else "")
        t = Target(agent=ad.agent, session=self.session, bin=shutil.which("claude") or "", config_dir=self.config_dir)
        if "deliver" not in ad.capabilities(t):
            raise DeliveryError(CLEARED.format(id=self.session))
        ad.deliver(t, message, Job(None, "relay", "", "").run, msg_id=msg_id)

    def ack(self, id: str, error: str | None) -> bool:
        """Whether the hub still waited for the Tell: a 404 says it expired or was acked, which is no reason to
        drop the stream."""
        body = {"doc": self.doc, "id": id, "outcome": "failed" if error else "delivered"}
        if error:
            body["error"] = error[:500]
        req = self._request(f"{self.hub}/_/relay", json.dumps(body).encode("utf-8"),
                            **{"Content-Type": "application/json"})
        try:
            with self._open(req, timeout=30):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def once(self):
        """One stream, to its end. Gone when the hub refuses the token or ends the fork."""
        req = self._request(f"{self.hub}/_/relay?doc={quote(self.doc, safe='/')}", Accept="text/event-stream")
        try:
            res = self._open(req, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):
                raise Gone("the hub refused the relay token: fork the session again") from None
            raise
        with res:
            for name, data in events(res):
                if name == "gone":
                    raise Gone("the fork is no longer this sheaf's live session")
                if name != "tell":
                    continue
                try:
                    t = json.loads(data)
                    id, message = t["id"], t["message"]
                except (ValueError, KeyError, TypeError):
                    continue
                if not (isinstance(id, str) and UUID_RE.fullmatch(id) and isinstance(message, str)):
                    continue
                try:
                    self._deliver(message, id)
                    error = None
                except DeliveryError as e:
                    error = str(e) or "not delivered"
                waited = self.ack(id, error)
                _err(f"sheaf relay: Tell {id} {'not delivered: ' + error if error else 'delivered'}"
                     + ("" if waited else "; the hub was no longer waiting for it (it expired, or was acked)"))

    def run(self) -> int:
        tries = 0
        while True:
            started = time.monotonic()
            try:
                self.once()
            except Gone as e:
                _err(f"sheaf relay: {e}")
                return EXIT_FAILED
            except (OSError, urllib.error.URLError) as e:
                _err(f"sheaf relay: the hub is unreachable ({getattr(e, 'reason', None) or e}): trying again")
            # A stream that ran a while (the front ends each after 5 minutes) is followed by a try at once.
            tries = 0 if time.monotonic() - started > 60 else tries + 1
            if tries:
                self._sleep(BACKOFF[min(tries, len(BACKOFF)) - 1])


def cmd_relay(argv: list[str]) -> int:
    if argv[:1] == ["revoke"]:
        return _revoke(argv[1:])
    # A token typed on the command line is in the shell's history and in every process listing: refused before
    # argparse, which would print it back in its error.
    if any(TOKEN_RE.search(a) for a in argv):
        _err("sheaf: the relay token goes in a file, --token-file FILE, never on the command line")
        return EXIT_USAGE
    p = argparse.ArgumentParser(
        prog="sheaf relay", allow_abbrev=False,
        usage="sheaf relay --hub ORIGIN --doc ADDRESS --session ID --token-file FILE [--config-dir DIR]\n"
              "       sheaf relay revoke ADDRESS",
        description="Take the Tells of one sheaf for your fork of its session, and hand each to that session.")
    p.add_argument("--hub", required=True, metavar="ORIGIN", help="the front's origin, https://...")
    p.add_argument("--doc", required=True, metavar="ADDRESS", help="the sheaf's address")
    p.add_argument("--session", required=True, metavar="ID", help="the fork's session id")
    p.add_argument("--token-file", required=True, metavar="FILE", help="the relay token, in a 0600 file of yours")
    p.add_argument("--config-dir", metavar="DIR",
                   help="where the session keeps its record (default: CLAUDE_CONFIG_DIR, else ~/.claude)")
    args = p.parse_args(argv)
    # The token goes in every request: over https, or plain http to this machine only.
    if not re.fullmatch(r"https://[^/?#\s]+|http://(127\.0\.0\.1|localhost|\[::1\])(:[0-9]+)?", args.hub):
        _err("sheaf: --hub must be an origin: https:// and a host, no path (http:// only for this machine)")
        return EXIT_USAGE
    if not UUID_RE.fullmatch(args.session):
        _err("sheaf: --session must be a session id (a lowercase UUID)")
        return EXIT_USAGE
    try:
        token = read_token(args.token_file)
    except Refused as e:
        _err(f"sheaf: {e}")
        return EXIT_USAGE
    config_dir = args.config_dir if args.config_dir is not None else str(config_dir_of(os.environ))
    r = Relay(args.hub, args.doc, args.session, token, config_dir)
    r.sender = Sender()
    try:
        return r.run()
    except KeyboardInterrupt:
        return EXIT_OK
    finally:
        r.sender.close()


def _revoke(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="sheaf relay revoke", usage="sheaf relay revoke ADDRESS",
                                description="End every relay token of a sheaf (run as the hub's account).")
    p.add_argument("address")
    args = p.parse_args(argv)
    from .hub.relay import Relays
    n = Relays().revoke(args.address)
    print(f"revoked {n} relay token{'' if n == 1 else 's'} of {args.address}")
    return EXIT_OK


COMMANDS.update({"relay": cmd_relay})
COMMAND_HELP.update({
    "relay": ("relay --hub ORIGIN --doc ADDRESS --session ID --token-file FILE | relay revoke ADDRESS",
              "take a sheaf's Tells for your fork of its session; revoke: end a sheaf's relay tokens"),
})
