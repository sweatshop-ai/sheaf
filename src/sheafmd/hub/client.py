"""
sheafmd.hub.client — how a command reaches the hub (SPEC 8.4, 9.4).

A command never sends the key to whatever answers on the port. It asks `GET /_/health?nonce=N`
first and checks `proof == HMAC-SHA256(key, "health:" + N)`; only an answer that proves it holds
this key is trusted with the key header or the sign-in URL. Something that answers otherwise (or
at all, without being sheaf) is an `Impostor`; something that does not answer (a timeout, a
connection reset or closed with no answer) is a `HubSilent`, which fails closed the same way (a hub that
proved itself and then ended the connection twice is its subclass `HubHungUp`); and a hub that proved
itself and then went before it answered the request is a `HubLost`.

Every request that carries the key (`call`, `door`) asks for the proof on the connection that then
carries it, so the process that proved it holds the key is the process that is sent it; a hub
replaced between two connections cannot be. `challenge` is the one proof that sends no key: it
is how a command learns whether a hub runs.

The hub is started here too: the first command that needs one and finds none spawns it,
detached, and waits for it to answer.
"""
import hmac
import http.client
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from .. import __version__, config, paths
from .auth import Auth

# A hub's start is its imports, 0.75 s of a free core: sixteen starts at once on two cores answer after
# 3.4 s at the median and 9 s at the worst, and a slow disk or a busy laptop is the same.
START_WAIT = 20.0
UPGRADE_WAIT = 20.0                   # for the new version to answer after an upgrade stop (14.4)
# More than jobs.TERM_GRACE + 1 s: a hub stop gives a child that ignores SIGTERM the grace, then a second
# after the SIGKILL (`Jobs.kill_all`), then writes its exit row (8.10).
STOP_WAIT = 8.0
TIMEOUT = 3.0
DOOR_TIMEOUT = 130.0             # a reply re-renders the page; pandoc is given 120 s (SPEC 3.2)
DOOR_ANSWER_MAX = 64 * 1024 * 1024
ANSWER_MAX = 1024 * 1024
_AGENT_ENV_PREFIXES = ("CLAUDE", "CODEX_", "CURSOR_", "GEMINI_", "OPENCODE")
HINT = "tip: sheaf service install keeps the hub running across reboots"


class Impostor(Exception):
    """Something answers on the hub's port that is not the hub that holds this key."""

    def __init__(self, port: int, message: str | None = None):
        super().__init__(message or f"something else holds 127.0.0.1:{port}, not your sheaf hub")
        self.port = port


class HubSilent(Impostor):
    """Nothing answered the challenge: the connection timed out, or was reset or closed with no
    answer; or, for a request, the hub proved itself and then ended the connection, twice, so that
    nothing could be sent (`HubHungUp`). No answer is not an answer (SPEC 9.4), so it fails closed
    like an `Impostor`, which every caller already handles, and the key goes nowhere; but a hub that
    does not run for a moment (a starved machine, a laptop that slept) is no stranger, and the
    message says so."""

    def __init__(self, port: int, waited: float | None = None, ending: str | None = None,
                 message: str | None = None):
        within = f" within {waited:g} s" if waited else ""
        ending = f", and {ending}" if ending else "; try again, or run `sheaf restart`"
        super().__init__(port, message or f"the sheaf hub on 127.0.0.1:{port} did not answer{within}{ending}")
        self.waited = waited

    def not_stopped(self, verb: str, why: str) -> "HubSilent":
        """The same silence, as `sheaf <verb>` reports it when it looked for a process to stop and found
        none (8.4): it says why, and not "run `sheaf restart`", which is what just refused."""
        return HubSilent(self.port, self.waited, f"`sheaf {verb}` stopped nothing: {why}")


class HubHungUp(HubSilent):
    """The hub answered the proof, and then ended the connection, twice: the proof is fine and
    nothing was sent. `HubSilent`'s "did not answer" is true of the request, not of the proof."""

    def __init__(self, port: int):
        super().__init__(port, message=f"the sheaf hub on 127.0.0.1:{port} proved itself and then ended the "
                                       "connection, twice, and nothing was sent; try again, or run `sheaf restart`")


class HubLost(Impostor):
    """The hub proved itself and then went before it answered a request: it was not there to take
    it (refused: nothing was sent), or it took it and the connection was reset or closed or timed
    out (a reset, a close, no answer in time: the request may have been applied). Not a stranger
    and not silent, but what a command does is the same, and every command already does it for an
    `Impostor`: a `  !` line and exit 1."""

    def __init__(self, port: int, sent: bool, waited: float | None = None):
        if not sent:
            message = f"the sheaf hub on 127.0.0.1:{port} stopped before this request; nothing was sent. Try again"
        else:
            how = f"did not answer within {waited:g} s" if waited else "ended the connection before it answered"
            message = (f"the sheaf hub on 127.0.0.1:{port} proved itself and then {how}; the request may have "
                       "been applied, so look at the result before you run it again")
        super().__init__(port, message)


class HubDidNotStart(Exception):
    pass


class NotSent(Exception):
    """The connection that proved the hub ended before the request went on it: nothing was sent."""


class JobsRunning(Exception):
    """The hub would not stop for an upgrade: an Ask or Tell started after the command looked."""


class SignInRefused(Exception):
    """The hub would not make a one-time sign-in link (an older hub that has no such route, or one
    that will not); the message says what it answered."""


STOPPING = "the hub is stopping"       # the error of the 503 a hub gives a kept connection once its stop has begun


def hub_is_stopping(status: int, body: bytes) -> bool:
    """Whether this answer is that 503: the hub applied nothing of the request and is about to exit."""
    if status != 503:
        return False
    try:
        out = json.loads(body)
    except ValueError:
        return False
    return isinstance(out, dict) and out.get("error") == STOPPING


def _ended_after_its_proof(c: http.client.HTTPConnection) -> bool:
    """Whether the hub has ended `c` since it answered on it. With `Connection: close` the connection
    is closed here already; without a word, a FIN or a reset is waiting on the socket, and a peek of
    one byte finds it (`b""` is the FIN) without reading anything. A hub that ends the connection
    in the instant after the peek is found out by the request, which says it may have been applied.
    Leaves the socket's timeout at 0: the caller sets the one its request needs."""
    if c.sock is None:
        return True
    c.sock.settimeout(0)
    try:
        return c.sock.recv(1, socket.MSG_PEEK) == b""
    except BlockingIOError:                           # nothing waits to be read: the hub has not hung up
        return False
    except OSError:                                   # a reset
        return True


class HubClient:
    def __init__(self, key: str, port: int):
        self.key, self.port = key, port
        self._auth = Auth(key, port)

    def _send_proved(self, method, path, data, headers, answer_within, answer_max) -> tuple[int, bytes]:
        """One request that carries the key, on the connection that has just proved the hub (9.4).
        Raises what `_prove_on` raises, `NotSent` when the connection ended after the proof, said or
        not (nothing was sent: `auto_open` is off, so nothing reopens it), and the sockets' own errors
        once the request may have gone. `answer_within` is how long the hub has to answer it."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=TIMEOUT)
        try:
            self._prove_on(c)
            c.auto_open = 0                           # the request goes on this connection or on none
            if _ended_after_its_proof(c):
                raise NotSent
            c.sock.settimeout(answer_within)
            c.request(method, path, data, headers)
            r = c.getresponse()
            return r.status, r.read(answer_max)
        finally:
            c.close()

    def challenge(self) -> dict | None:
        """The hub's health answer once it has proved it holds this key; None when nothing
        listens on the port. Raises Impostor for anything else, and its subclass HubSilent when
        nothing answered in time or the connection was reset."""
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=TIMEOUT)
        try:
            return self._prove_on(c)
        except ConnectionRefusedError:
            return None
        finally:
            c.close()

    def _prove_on(self, c: http.client.HTTPConnection) -> dict:
        """Ask for the proof on `c` and check it. ConnectionRefusedError when nothing listens,
        HubSilent when nothing answered in time or the connection was reset, Impostor for
        anything else that is not the hub that holds this key."""
        nonce = secrets.token_hex(16)
        try:
            c.request("GET", f"/_/health?nonce={nonce}")
            r = c.getresponse()
            status, data = r.status, r.read(ANSWER_MAX)
        except ConnectionRefusedError:
            raise
        except TimeoutError:
            raise HubSilent(self.port, TIMEOUT) from None
        except ConnectionError:          # a reset, or a close with no answer (RemoteDisconnected is one)
            raise HubSilent(self.port) from None
        except (OSError, http.client.HTTPException):
            raise Impostor(self.port) from None
        try:
            got = json.loads(data)
            ok = (status == 200 and isinstance(got, dict) and got.get("app") == "sheaf"
                  and hmac.compare_digest(str(got.get("proof", "")), self._auth.proof(nonce)))
        except (ValueError, TypeError):
            ok = False
        if not ok:
            raise Impostor(self.port)
        return got

    def call(self, method: str, path: str, body=None) -> tuple[int, dict]:
        """A request with the key header. The hub proves itself (9.4) on the connection that then
        carries the request. Raises Impostor when what answers is not the hub; HubSilent when nothing
        answers the proof in time; HubHungUp when the hub ends the connection after its proof twice (the
        second time on a connection of its own: a hub that ended one is asked again); and HubLost when
        the hub is gone by the request, or does not answer it. Every one is an Impostor, which is what a
        command stops at, so a command never meets a socket's own error."""
        data = None if body is None else json.dumps(body).encode()
        headers = {"X-Sheaf-Key": self.key, **({} if data is None else {"Content-Type": "application/json"})}
        for _ in range(2):
            try:
                status, answer = self._send_proved(method, path, data, headers, TIMEOUT, ANSWER_MAX)
            except NotSent:
                continue
            except ConnectionRefusedError:               # nothing listens by now: nothing was sent
                raise HubLost(self.port, sent=False) from None
            except TimeoutError:
                raise HubLost(self.port, sent=True, waited=TIMEOUT) from None
            except (OSError, http.client.HTTPException):
                raise HubLost(self.port, sent=True) from None
            if hub_is_stopping(status, answer):          # it applied nothing, and is not sent to again
                raise HubLost(self.port, sent=False)
            try:
                out = json.loads(answer)
            except ValueError:
                out = {"ok": False, "error": f"the hub answered {status} with something that is not JSON"}
            return status, out if isinstance(out, dict) else {"ok": False}
        raise HubHungUp(self.port)

    def door(self, raw: bytes, display: str) -> tuple[int, bytes]:
        """One JSON-RPC message to `POST /_/mcp`, with the key and the name its reply is signed
        with. The name travels percent-encoded: a header holds no more than Latin-1.

        The hub proves itself (9.4) on the connection that then carries the message, so what holds
        the key is the process that proved it: a hub replaced between two connections cannot be
        sent it. Raises ConnectionRefusedError when nothing listens, Impostor when what answers is
        not the hub, `NotSent` when the connection ended after the proof (nothing was sent), and
        the sockets' own errors once the message may have been."""
        return self._send_proved("POST", "/_/mcp", raw, {"Content-Type": "application/json",
                                                          "X-Sheaf-Key": self.key,
                                                          "X-Sheaf-As": quote(display, safe=" ")},
                                 DOOR_TIMEOUT, DOOR_ANSWER_MAX)

    def sign_in_url(self, next_path: str) -> str:
        """The URL that holds the key: for `sheaf signin-url` alone, which prints it for a person
        to open on another machine (SPEC 9.3, D13)."""
        return f"http://127.0.0.1:{self.port}/_/open?key={self.key}&next={quote(next_path, safe='/')}"

    def one_time_sign_in_url(self, next_path: str) -> str:
        """The URL `sheaf open` gives the browser: it carries a nonce the hub minted for this
        call, good once and for about 30 seconds, never the key. The call that asks for the nonce
        proves the hub first (`call`): an Impostor, a HubSilent or a HubLost from it (the hub went
        before it answered) is not a refusal of the link, and is raised as it is. `SignInRefused` is
        what the hub itself said: no such route, or a link it would not make."""
        status, res = self.call("POST", "/_/signin")
        nonce = res.get("nonce")
        if status != 200 or not res.get("ok") or not isinstance(nonce, str):
            raise SignInRefused(res.get("error") or f"the hub answered {status}")
        return f"http://127.0.0.1:{self.port}/_/open?nonce={nonce}&next={quote(next_path, safe='/')}"


def client() -> HubClient:
    """A client for this user's hub, making the key first if there is none."""
    return HubClient(paths.ensure_key(), config.port())


def _clean_env() -> dict:
    """The environment of a hub: the user's own, without any agent's variables, so the hub and
    the Ask children it will start never inherit one session (SPEC 8.4)."""
    return {k: v for k, v in os.environ.items() if not k.startswith(_AGENT_ENV_PREFIXES)}


def spawn_hub(started_by: str):
    home = Path.home()
    subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", started_by],
                     cwd=home if home.is_dir() else "/", env=_clean_env(),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True)


_VERSION = re.compile(r"^(\d+(?:\.\d+)*)(.*)$")


def compare_versions(a, b) -> int | None:
    """1 when `a` is newer than `b`, -1 when older, 0 when the same; None when either is not a
    version (a number, dots, then at most a suffix). A suffix (`.dev0`, `rc1`) is a pre-release:
    older than the same numbers without one."""
    def key(v):
        m = _VERSION.match(v.strip()) if isinstance(v, str) else None
        if not m:
            return None
        nums = [int(x) for x in m.group(1).split(".")]
        while len(nums) > 1 and nums[-1] == 0:
            nums.pop()
        return nums, 0 if m.group(2) else 1, m.group(2)
    ka, kb = key(a), key(b)
    if ka is None or kb is None:
        return None
    return (ka > kb) - (ka < kb)


def ended(pid: int) -> bool:
    """Whether the process `pid` has ended. A hub that this very process started is its child
    and stays a zombie until reaped, so reap it first; a hub started from a shell is nobody's
    child, and `waitpid` says so."""
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def stop_and_explain(c: HubClient, got: dict, reason: str, force: bool = False) -> str:
    """Ask the hub `got` to stop and wait for it to end, its exit row written. "" when it ended;
    otherwise a few plain words on what was there when STOP_WAIT ran out: that it refused, that a
    hub still answers (this one or another), that the process it waited for still runs. Never the
    hub's own text. An upgrade stop that is not `force`d (`sheaf restart` forces its own) is
    refused while an Ask or Tell runs, which raises JobsRunning."""
    from . import server
    info = server.read_pid_file() or {}
    pid = info.get("pid") if info.get("boot") == got.get("boot") and info.get("pid") != os.getpid() else None
    status, res = c.call("POST", "/_/stop", {"reason": reason, **({"force": True} if force else {})})
    if status == 409 and reason == "upgrade" and not force:
        raise JobsRunning(res.get("error") or "an Ask or Tell is running")
    if status != 200 or not res.get("ok"):
        return "it refused the stop"
    deadline = time.time() + STOP_WAIT
    while True:
        try:
            now = c.challenge()
        except Impostor:
            now = None
        alive = pid is not None and not ended(pid)
        if now is None and not alive:
            return ""
        seen = [] if now is None else ["still answering" if now.get("boot") == got.get("boot")
                                       else "another hub answers"]
        if alive:
            seen.append(f"process {pid} is still running")
        if time.time() >= deadline:
            return " and ".join(seen)
        time.sleep(0.05)


def wait_for_start(c: HubClient, wait: float, wanted=lambda got: True) -> dict | None:
    """Challenge the hub on `c`'s port until it gives an answer `wanted` takes, for `wait` seconds: what a
    start waits with. A hub that is starting listens from its bind on and answers once it serves
    (`server.run`), so a silence in between is a hub that is not there yet, and it is asked again. None
    when nothing `wanted` answered; when the last challenge of the wait met a silence, that silence
    (9.4). Anything else that answers on the port raises Impostor at once."""
    deadline = time.time() + wait
    while True:
        try:
            got, silent = c.challenge(), None
        except HubSilent as e:
            got, silent = None, e
        if got is not None and wanted(got):
            return got
        if time.time() >= deadline:
            if silent is not None:
                raise silent
            return None
        time.sleep(0.05)


def stop_and_wait(c: HubClient, got: dict, reason: str, force: bool = False) -> bool:
    """`stop_and_explain` for a caller that needs only whether the hub ended."""
    return not stop_and_explain(c, got, reason, force)


def _meet_version(c: HubClient, got: dict, warn) -> tuple[dict, bool]:
    """A hub of another version (8.4): a newer command restarts an idle hub (14.4), says so when
    a job runs, and an older command only says so. Returns the hub to use and whether this call
    started one."""
    theirs = got.get("version")
    order = compare_versions(__version__, theirs)
    if order == 0:
        return got, False
    mismatch = f"  ! the hub runs {theirs}, this is {__version__}"
    if order != 1:                                      # older command, or a version nobody can read
        warn(mismatch)
        return got, False
    status, jobs = c.call("GET", "/_/jobs")
    if status != 200:                                   # cannot tell whether a job runs: leave it
        warn(mismatch)
        return got, False
    if jobs.get("asking") or jobs.get("telling"):
        warn(f"  ! the hub runs {theirs} and an Ask or Tell is running; this is {__version__}. "
             "Run sheaf restart when it is done.")
        return got, False
    try:
        left = stop_and_explain(c, got, "upgrade")
    except JobsRunning:                                 # a job started after the look at /_/jobs
        warn(f"  ! the hub runs {theirs} and an Ask or Tell is running; this is {__version__}. "
             "Run sheaf restart when it is done.")
        return got, False
    if left:
        raise HubDidNotStart(f"the hub did not stop for the upgrade ({left}; see `sheaf diag`)")
    if not got.get("service"):                          # under the service, exit 75 starts the new code
        spawn_hub("upgrade")
    now = wait_for_start(c, UPGRADE_WAIT, lambda now: now.get("version") == __version__)
    if now is None:
        raise HubDidNotStart("the hub did not come back on the new version; see `sheaf diag`")
    return now, True


def ensure_hub(started_by: str, say=print, warn=None) -> tuple[HubClient, bool]:
    """The client of a hub that has proved itself, and whether this call started it.

    Starts one when none runs. The first time a command starts a hub it prints the one-line
    tip about the user service and leaves a marker. A hub of another version meets the version
    rule (`_meet_version`)."""
    warn = warn or say
    c = client()
    got = c.challenge()
    started = False
    if got is None:
        spawn_hub(started_by)
        started = True
        got = wait_for_start(c, START_WAIT)
        if got is None:
            raise HubDidNotStart("the hub did not start; see `sheaf diag`")
        marker = paths.state_dir() / "service-hint-shown"
        if not marker.exists():
            say(f"  {HINT}")
            try:
                marker.touch(mode=0o600)
            except OSError:
                pass
    got, restarted = _meet_version(c, got, warn)
    return c, started or restarted


class HubUnavailable(Exception):
    """The hub cannot be reached, or is not one this key belongs to. The message says why, in a
    sentence an agent can pass on."""


class DoorLink:
    """What `sheaf mcp` holds to the hub: it finds the hub (starting one when none runs) and
    posts each message with the key and the agent's name. The door lives as long as the agent
    does, so the hub proves itself (9.4) before every message, not once: what answers on the
    port later may not be the hub that did. The proof and the message go on one connection
    (`HubClient.door`), so nothing can take the port between them. A hub that went away, or a
    key that was rotated meanwhile, is found again once per message. A message that may have
    reached the hub is never sent twice: when its answer is lost, the message fails and says so."""

    def __init__(self, display: str, say=print):
        self.display, self._say = display, say
        self._client: HubClient | None = None

    def connect(self):
        try:
            self._client, _ = ensure_hub("mcp", say=self._say, warn=self._say)
        except HubLost as e:                         # the door's own look at the hub: no message was sent
            self._client = None
            raise HubUnavailable(f"the sheaf hub on 127.0.0.1:{e.port} went while the door was checking it, "
                                 "before any message of yours was sent; try again") from None
        except (Impostor, HubDidNotStart) as e:
            self._client = None
            raise HubUnavailable(str(e)) from None

    def post(self, raw: bytes) -> tuple[int, bytes]:
        first_try_hung_up = False                      # the hub ended the connection after its proof
        for attempt in (1, 2):
            if self._client is None:
                self.connect()
            try:
                status, body = self._client.door(raw, self.display)
            except Impostor as e:
                self._client = None
                if attempt == 1:
                    continue                 # `sheaf rotate`: read the key again; a stranger fails that proof too
                raise HubUnavailable(str(e)) from None
            except NotSent:
                port = self._client.port
                self._client = None                        # the message reached nothing: safe to send again
                if first_try_hung_up:
                    raise HubUnavailable(str(HubHungUp(port))) from None     # the words of a command (9.4)
                first_try_hung_up = attempt == 1
                continue
            except ConnectionRefusedError:
                self._client = None                        # the message reached nothing: safe to send again
                continue
            except (OSError, http.client.HTTPException):
                self._client = None
                raise HubUnavailable(
                    "the hub did not answer, and this message may have been applied: read the "
                    "document again before sending it a second time") from None
            if status == 401 and attempt == 1:
                self._client = None          # `sheaf rotate`: read the key again
                continue
            if hub_is_stopping(status, body):
                self._client = None
                raise HubUnavailable(f"{STOPPING}, nothing of yours was sent; try again in a moment")
            return status, body
        raise HubUnavailable("the hub is not reachable; see `sheaf diag`")
