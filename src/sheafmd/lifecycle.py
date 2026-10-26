"""
sheafmd.lifecycle — the commands that run the hub for real (SPEC 8.4, 9.3, 14.3).

    sheaf restart       stop the hub and start it again
    sheaf rotate        replace the hub key; every browser signs in again
    sheaf signin-url    print the URL that signs a browser in, for a box you reach over ssh
    sheaf service       install or remove the user service

Each is a function `(argv) -> exit code`, registered in COMMANDS and given its usage line in
COMMAND_HELP, which the foot of cli.py merges into its own. This module does not import cli.py:
cli.py imports this one.
"""
import argparse
import sys

from . import agent_setup, paths
from .agents.detect import detect
from .hub import client as hubclient
from .hub import recover
from .hub import server as hubserver
from .hub import service

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

COMMANDS: dict = {}
COMMAND_HELP: dict = {}


def _out(line: str = ""):
    print(line)


def _err(line: str = ""):
    print(line, file=sys.stderr)


def _parser(name: str, usage: str, what: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"sheaf {name}", usage=f"sheaf {usage}", description=what)


def _hub_failure(e: Exception) -> int:
    if isinstance(e, hubclient.Impostor):
        _err(f"  ! {e}")
    else:
        _err(f"sheaf: {e}")
    return EXIT_FAILED


# ── a hub that holds its port and does not answer (8.4, 9.4) ─────────────────

def recover_silent_hub(c: hubclient.HubClient, silent: hubclient.HubSilent, verb: str) -> bool:
    """`stop` and `restart` met a hub that holds the port and did not answer (`silent`). Stop the
    process the pid file names when the rule of `recover` holds, and say in one line what was
    stopped and why. Returns False then: the process is gone and the caller goes on as if no hub ran.

    A hub the service runs is not signalled; the service manager is asked to `verb` it (`stop` or
    `restart`) and True is returned, so a caller that was about to ask does not ask twice. With no
    service installed that hub is left alone, like any other the rule does not name. Where nothing is
    stopped, the silence is raised again with the reason in its one line (`HubSilent.not_stopped`):
    the command's message no longer sends the person to `sheaf restart`, which just refused."""
    try:
        hub = recover.find(c.port)
    except recover.Refusal as e:
        raise silent.not_stopped(verb, str(e)) from None
    if hub.supervised:
        try:
            there = service.installed()
        except service.ServiceError as e:
            raise silent.not_stopped(verb, f"pid {hub.pid} is the service's hub, and sheaf {e}") from None
        if not there:
            raise silent.not_stopped(verb, f"pid {hub.pid} is the service's hub and the service is not installed")
        _out(f"  the sheaf hub (pid {hub.pid}) on 127.0.0.1:{c.port} did not answer; "
             f"asking the service to {verb} it")
        try:
            service.control(verb)
        except service.ServiceError as e:
            raise hubclient.HubDidNotStart(str(e)) from None
        return True
    ended = hub.stop()
    said = f"  stopped the sheaf hub (pid {ended.pid}) that held 127.0.0.1:{c.port} and did not answer"
    if ended.killed:
        said += f"; it ignored SIGTERM for {ended.grace:g} s and was killed"
    _out(said)
    if not ended.ended:
        raise hubclient.HubDidNotStart(f"the hub (pid {ended.pid}) did not end, not even on SIGKILL; "
                                       "see `sheaf diag`")
    return False


# ── start and restart through the service, and restart ───────────────────────

def _running(c: hubclient.HubClient) -> int:
    info = hubserver.read_pid_file() or {}
    _out(f"  hub running on 127.0.0.1:{c.port} (pid {info.get('pid', '?')})")
    return EXIT_OK


def _running_or_failure(cannot_tell: Exception) -> int:
    """`start` when whether the service is installed cannot be told: a hub already running is the
    answer, as it is with the service installed or without it; else the refusal."""
    try:
        c = hubclient.client()
        if c.challenge() is not None:
            return _running(c)
    except hubclient.Impostor as e:
        return _hub_failure(e)
    return _hub_failure(cannot_tell)


def _take_back_restart(c: hubclient.HubClient):
    """The service manager failed to restart the hub that was told it would: tell it the restart is
    not coming, so that a logout or a `systemctl stop` in the next RESTART_TOLD_TTL is not taken for
    it (8.4). A hub of the version before has no such route (405) and keeps the announcement for its
    30 s, as it did; a hub that is gone by now has nothing to forget. Neither changes what the
    command says: the manager's failure."""
    try:
        c.call("DELETE", "/_/restarting")
    except hubclient.Impostor:
        pass


def via_service(verb: str) -> int | None:
    """`start` or `restart` of an installed service goes through it (SPEC 14.3). None when the
    service is not installed: the caller does what it always did. `start` with a hub already
    running asks nothing of the service. A `restart` that meets a hub that holds the port and does
    not answer recovers it first (`recover_silent_hub`, SPEC 8.4); `start` says what it always said."""
    try:
        if not service.installed():
            return None
    except service.ServiceError as e:      # it cannot be told: neither around the service nor through it
        return _running_or_failure(e) if verb == "start" else _hub_failure(e)
    asked = told = False
    try:
        c = hubclient.client()
        try:
            before = c.challenge()
        except hubclient.HubSilent as silent:
            if verb != "restart":
                raise
            asked = recover_silent_hub(c, silent, verb)         # True: the manager was asked; False: stopped here
                                                                # (HubDidNotStart when it did not end, a HubSilent that says why when it may not)
            before = None
        if verb == "start" and before is not None:
            return _running(c)
        if verb == "restart" and before is not None:
            if before.get("service"):
                # Tell the hub its reason now: the service manager's SIGTERM would be a "signal",
                # and open tabs would show the stop banner (8.4). An older hub has no such route.
                c.call("POST", "/_/restarting")
                told = True
            else:
                _make_room("upgrade")           # a hub a command started holds the port the service needs
                before = None
        if not asked:
            try:
                service.control(verb)
            except service.ServiceError:
                if told:
                    _take_back_restart(c)
                raise
        got = hubclient.wait_for_start(
            c, hubclient.START_WAIT, lambda got: before is None or got.get("boot") != before.get("boot"))
    except (hubclient.Impostor, hubclient.HubDidNotStart, service.ServiceError) as e:
        return _hub_failure(e)
    if got is None:
        _err("sheaf: the service did not bring the hub up; see `sheaf diag` and "
             f"`{service.status_command()}`")
        return EXIT_FAILED
    info = hubserver.read_pid_file() or {}
    _out(f"  hub started on 127.0.0.1:{c.port} (pid {info.get('pid', '?')})")
    return EXIT_OK


def cmd_restart(argv: list[str]) -> int:
    _parser("restart", "restart", "Stop the hub and start it again: the new code after an upgrade."
            ).parse_args(argv)
    done = via_service("restart")
    if done is not None:
        return done
    try:
        c = hubclient.client()
        recovered = False
        try:
            got = c.challenge()
        except hubclient.HubSilent as silent:
            recover_silent_hub(c, silent, "restart")        # stopped here, or raises (a HubSilent that says why, HubDidNotStart)
            got, recovered = None, True
        # An upgrade stop, not a plain one: open tabs ride through it as through an outage, with
        # no "the hub was stopped" banner for a hub that is back in a second (8.4, 10.7).
        if got is not None and not hubclient.stop_and_wait(c, got, "upgrade", force=True):
            _err("sheaf: the hub did not stop; see `sheaf diag`")
            return EXIT_FAILED
        c, _ = hubclient.ensure_hub("cli", _out, _err)
    except (hubclient.Impostor, hubclient.HubDidNotStart) as e:
        return _hub_failure(e)
    info = hubserver.read_pid_file() or {}
    _out(f"  hub {'restarted' if got is not None or recovered else 'started'} on 127.0.0.1:{c.port} "
         f"(pid {info.get('pid', '?')})")
    return EXIT_OK


# ── rotate and signin-url (9.3) ──────────────────────────────────────────────

def cmd_rotate(argv: list[str]) -> int:
    _parser("rotate", "rotate", "Replace the hub key. Every browser signs in again; nothing else changes."
            ).parse_args(argv)
    again = "browsers sign in again with sheaf open or sheaf signin-url"
    try:
        c = hubclient.client()
        with paths.key_lock():             # a hub that is starting has read the key or waits for this
            got = c.challenge()
            if got is None:
                # Nobody holds the old key, so the file is replaced where it lies.
                paths.rotate_key()
                _out(f"  no hub is running; the key was replaced in the file; {again}")
                return EXIT_OK
        status, res = c.call("POST", "/_/rotate")
    except hubclient.Impostor as e:
        return _hub_failure(e)
    if status != 200 or not res.get("ok"):
        _err(f"sheaf: the hub did not rotate its key: {res.get('error') or status}")
        return EXIT_FAILED
    _out(f"  key rotated; {again}")
    return EXIT_OK


AGENT_WARNING = "  ! this URL holds your hub key; open it yourself, never paste it to an agent"


def cmd_signin_url(argv: list[str]) -> int:
    _parser("signin-url", "signin-url", "Print the URL that signs a browser in to the hub. It holds the "
            "hub key: the one command that prints it, for a hub on another machine.").parse_args(argv)
    try:
        c, _ = hubclient.ensure_hub("cli", _err, _err)       # stdout holds the URL and nothing else
    except (hubclient.Impostor, hubclient.HubDidNotStart) as e:
        return _hub_failure(e)
    if detect() is not None:
        _err(AGENT_WARNING)
    _out(c.sign_in_url("/"))
    return EXIT_OK


# ── the user service (14.3) ──────────────────────────────────────────────────

def _make_room(reason: str = "stop"):
    """A hub that a command started holds the port the service needs: stop it, so the service
    starts the hub in its place. A hub the service already runs is left alone. `install` stops
    it with a plain stop; `restart` with an upgrade stop, so open tabs ride through (8.4)."""
    c = hubclient.client()
    got = c.challenge()
    if got is None or got.get("service"):
        return
    _out("  stopping the hub that is running, so the service can take its place")
    if not hubclient.stop_and_wait(c, got, reason, force=True):
        raise service.ServiceError("the hub that is running did not stop; run `sheaf stop` and try again")


def cmd_service(argv: list[str]) -> int:
    p = _parser("service", "service install|uninstall",
                "Install the user service that keeps the hub running across logins and reboots, "
                "or remove it.")
    p.add_argument("action", choices=["install", "uninstall"])
    args = p.parse_args(argv)
    try:
        if args.action == "install":
            service.install(_out, make_room=_make_room, install_line=agent_setup.install_advice)
        else:
            service.uninstall(_out)
    except hubclient.Impostor as e:
        return _hub_failure(e)
    except service.ServiceError as e:
        _err(f"sheaf: {e}")
        return EXIT_FAILED
    return EXIT_OK


COMMANDS.update({"restart": cmd_restart, "rotate": cmd_rotate, "signin-url": cmd_signin_url,
                 "service": cmd_service})
COMMAND_HELP.update({
    "restart": ("restart", "stop the hub and start it again"),
    "rotate": ("rotate", "replace the hub key; browsers sign in again"),
    "signin-url": ("signin-url", "print the URL that signs a browser in (it holds the hub key)"),
    "service": ("service install|uninstall", "keep the hub running as a user service"),
})
