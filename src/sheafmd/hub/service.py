"""
sheafmd.hub.service — the user service that keeps the hub running (SPEC 14.3, 14.4).

`sheaf service install` writes a systemd user unit (Linux) or a launchd agent (macOS) and starts
it; `uninstall` undoes that. It is offered, never run by install. The unit and the plist are
built here as text by pure functions, so a test reads them without a service manager; the
commands that run `systemctl` and `launchctl` find them only through PATH.

Restart, with a backoff, is the service manager's work. The unit says `Restart=always`, so a hub that
ends on a signal nobody announced is started again (#79), and `RestartPreventExitStatus` names the
one exit it leaves down: `sheaf stop`, which the hub ends with EXIT_STOPPED only when the unit says
so (STOP_EXIT_ENV), because a unit of an older sheaf restarts that code. `systemctl stop` is never
restarted. launchd has no per-code rule, so the plist keeps `KeepAlive.SuccessfulExit=false`, says
nothing, and a stop there exits 0: sheaf has to exit with a failure code when it crashes (1) or is
stopped for an upgrade (75, 14.4).
"""
import getpass
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import paths

LABEL = "io.github.sweatshop-ai.sheaf"
UNIT = "sheaf.service"
DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
# What an installer's environment carries into the service: the port and the home it chose, and on
# Linux the XDG folders its shell moved (SPEC 4.1: the hub must read the key the commands read).
# The paths on macOS ignore XDG, so the plist does not carry them.
CARRIED = ("SHEAF_PORT", "SHEAF_HOME")
CARRIED_XDG = ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME")
# What a hub under the unit exits with after `sheaf stop` (POST /_/stop {reason: "stop"}): the unit's
# one exit it does not restart, and a success, so a hub stopped on purpose is `inactive`, not `failed`.
# The unit says it in STOP_EXIT_ENV; a hub whose manager does not say it exits 0 on a stop.
EXIT_STOPPED = 3
STOP_EXIT_ENV = "SHEAF_STOP_EXIT"
# How long the manager waits for a stopping hub before SIGKILL (#95): past the hub's own bound (the jobs' grace,
# then the pushes due and the end of its git, hub/commits.py). `KillMode=mixed` signals the hub alone, not its git.
STOP_WAIT = 60
# How long an install or uninstall waits for launchd to let go of the job it booted out: the manager's wait for
# the stopping hub, then its SIGKILL.
BOOTOUT_WAIT = STOP_WAIT + 10


class ServiceError(Exception):
    """A message for a person: what could not be done, and what the tool said."""


def kind() -> str | None:
    """`systemd` on Linux, `launchd` on macOS, None elsewhere."""
    if sys.platform.startswith("linux"):
        return "systemd"
    if sys.platform == "darwin":
        return "launchd"
    return None


SCRIPT, MODULE = "sheaf", "sheafmd"        # the command, and the module `python -m` runs in its place


def sheaf_command() -> list[str]:
    """The absolute command that runs sheaf: the `sheaf` script that is running this (the service
    runs the sheaf that installed it, not another one first on PATH), else `sheaf` on PATH, else
    this Python with `-m sheafmd`."""
    argv0 = Path(sys.argv[0]) if sys.argv and sys.argv[0] else None
    if argv0 is not None and argv0.name == SCRIPT and argv0.is_file():
        return [os.path.abspath(argv0)]                 # as it was started: a symlink stays the one on PATH
    found = shutil.which(SCRIPT)
    if found:
        return [os.path.abspath(found)]
    return [sys.executable, "-m", MODULE]


# <cache>/archive-v0/<hash>/bin/sheaf, or <cache>/environments-v2/<hash>/bin/python: the shape of
# a temporary environment of uv, and not any folder that is named archive-v2.
_UV_ENVIRONMENT = re.compile(r"/(?:archive|environments)-v\d+/[^/]+/(?:bin|Scripts)/")
# <cache>/<15 hex>/bin/sheaf: a venv of `pipx run`, named by a hash of what it holds. pipx writes
# `pipx_metadata.json` into it, as into a venv it installs for good (`venvs/<package>`).
_PIPX_RUN = re.compile(r"/[0-9a-f]{15}/(?:bin|Scripts)/[^/]+$")
# How each tool's temporary copy goes, for a message.
_CACHE_GOES = {"uv": "which uv deletes when the cache is cleaned",
               "pipx": "which pipx deletes once it is 14 days old"}


def runs_from_a_cache(command: list[str]) -> str | None:
    """The tool whose temporary environment `command` is in, or None. `uv`: `uvx --from <source>
    sheaf ...` runs `<cache>/archive-v0/<hash>/bin/sheaf` (`uv run --with` runs
    `environments-v<n>/<hash>`), which `uv cache clean` and `uv cache prune` delete and a new
    revision replaces by another hash. `pipx`: `pipx run` runs `<cache>/<15 hex>/bin/sheaf` (its
    cache is `<pipx home>/.cache`, or `~/.cache/pipx` on a Linux with no pipx home), and deletes a
    venv there that is older than 14 days. A link into a cache counts too, because what it points
    at goes. A project's `.venv` is neither, though uv tags it CACHEDIR.TAG as well."""
    for path in (os.path.abspath(command[0]), os.path.realpath(command[0])):
        posix = Path(path).as_posix()
        if _UV_ENVIRONMENT.search(posix):
            return "uv"
        if _PIPX_RUN.search(posix) and (Path(path).parent.parent / "pipx_metadata.json").is_file():
            return "pipx"
    return None


def cache_refusal(tool: str, path: str) -> str:
    """The start of the refusal of a sheaf that runs from `tool`'s temporary copy at `path`."""
    return f"this sheaf runs from a temporary copy in {tool}'s cache ({path}), {_CACHE_GOES[tool]}."


# ── the unit and the plist, as text ──────────────────────────────────────────

def _word(text: str, *, command: bool = False) -> str:
    """One word of a unit file as systemd reads it: `%` is a specifier, `$` a variable in a
    command line, and a word with a space, a quote, a backslash or a `;` goes in double quotes."""
    text = text.replace("%", "%%")
    if command:
        text = text.replace("$", "$$")
    if re.search(r"[\s\"'\\;]", text):
        text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _env_line(name: str, value: str) -> str:
    return "Environment=" + _word(f"{name}={value}")


def systemd_unit(command: list[str], path_env: str, extra_env: dict | None = None) -> str:
    """The unit of SPEC 14.3. `command` is the absolute command that runs sheaf."""
    for text in (*command, path_env, *(extra_env or {}).values()):
        if "\n" in text or "\r" in text:
            raise ServiceError("a value with a line break cannot go into a service file")
    exec_start = " ".join([*(_word(c, command=True) for c in command), "hub", "--started-by", "service"])
    env = [_env_line("PATH", path_env), _env_line(STOP_EXIT_ENV, str(EXIT_STOPPED))] \
        + [_env_line(k, v) for k, v in (extra_env or {}).items()]
    return "\n".join([
        "[Unit]", "Description=sheaf hub", "StartLimitIntervalSec=300", "StartLimitBurst=5", "",
        "[Service]", f"ExecStart={exec_start}", "Restart=always",
        f"RestartPreventExitStatus={EXIT_STOPPED}", f"SuccessExitStatus={EXIT_STOPPED}", "RestartSec=2",
        "RestartSteps=5", "RestartMaxDelaySec=60", "KillMode=mixed", f"TimeoutStopSec={STOP_WAIT}", *env, "",
        "[Install]", "WantedBy=default.target", ""])


def launchd_plist(command: list[str], path_env: str, extra_env: dict | None = None) -> bytes:
    """The launchd agent of SPEC 14.3."""
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [*command, "hub", "--started-by", "service"],
        "EnvironmentVariables": {"PATH": path_env, **(extra_env or {})},
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 10,
        "ExitTimeOut": STOP_WAIT,
    })


# ── where the file goes, and whether it is there ─────────────────────────────

def unit_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base and os.path.isabs(base) else Path.home() / ".config"
    return root / "systemd" / "user" / UNIT


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def definition_path() -> Path | None:
    return {"systemd": unit_path, "launchd": plist_path}.get(kind() or "", lambda: None)()


def installed() -> bool:
    """Whether the service's file is there. A folder on the way that this account may not enter is
    no answer: ServiceError, naming the file, and the caller goes neither around the service nor
    through it."""
    f = definition_path()
    if f is None:
        return False
    try:
        return paths.is_file(f)
    except OSError as e:
        raise ServiceError(
            f"cannot tell whether the user service is installed: {f}: {e.strerror or e}") from None


def _domain() -> str:
    return f"gui/{os.getuid()}"


def status_command() -> str:
    """The command that shows what the service manager makes of the service, for a message."""
    if kind() == "systemd":
        return f"systemctl --user status {UNIT}"
    return f"launchctl print {_domain()}/{LABEL}"


# ── running the service manager ──────────────────────────────────────────────

def _tool() -> str:
    name = "systemctl" if kind() == "systemd" else "launchctl"
    if shutil.which(name) is None:
        why = "the user service needs systemd" if name == "systemctl" else "the user service needs launchd"
        raise ServiceError(f"{name} was not found on PATH; {why}")
    return name


def _run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    """Run a service-manager command, found through PATH only."""
    try:
        done = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise ServiceError(f"`{' '.join(argv)}` could not run: {e}") from None
    if check and done.returncode != 0:
        said = (done.stderr or done.stdout).strip()
        raise ServiceError(f"`{' '.join(argv)}` failed ({done.returncode})" + (f": {said}" if said else ""))
    return done


def _write(f: Path, data: bytes):
    """The whole file or none of it: written beside it, then moved into place."""
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f".{f.name}.new")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o644)
    os.replace(tmp, f)


def _environment() -> tuple[str, dict]:
    carried = CARRIED + CARRIED_XDG if kind() == "systemd" else CARRIED
    extra = {k: os.environ[k] for k in carried if os.environ.get(k)}
    return os.environ.get("PATH") or DEFAULT_PATH, extra


def install(say, make_room=lambda: None, *, install_line):
    """Write the definition and start the service. `make_room` runs just before the service is
    started: it stops a hub that a command started, which holds the port the service needs. A sheaf
    that runs from a temporary copy (`uvx`, `pipx run`) installs nothing: the service would run a
    path that goes. `install_line()` is the command that installs this sheaf for good, for that
    refusal, with the note that follows it when the source URL had a query or a fragment."""
    k = kind()
    if k is None:
        raise ServiceError("the user service is for Linux (systemd) and macOS (launchd)")
    tool = _tool()                    # before anything is written, and before the advice to install sheaf
    path_env, extra = _environment()
    command = sheaf_command()
    cache = runs_from_a_cache(command)
    if cache:                                         # before anything is written or asked
        raise ServiceError(f"{cache_refusal(cache, command[0])} A service started from that path "
                           f"would fail then, so none is installed. Install sheaf, then install the "
                           f"service again:\n  {install_line()}\n  sheaf service install")
    if k == "systemd":
        f = unit_path()
        unit = systemd_unit(command, path_env, extra).encode("utf-8")
        before = f.read_bytes() if f.is_file() else None
        _write(f, unit)
        _run([tool, "--user", "daemon-reload"])
        make_room()
        _run([tool, "--user", "enable", "--now", UNIT])
        say(f"  service installed: {f}")
        if before is not None and before != unit:
            # `enable --now` leaves a running hub as it is: it keeps the environment it started with
            # (STOP_EXIT_ENV), so until it starts again its `sheaf stop` exits 0, which the new unit restarts.
            say("  the unit changed; a hub the service is running takes it when it starts again: "
                "run `sheaf restart`")
        say(f"  On a remote box, ask the admin for `loginctl enable-linger {getpass.getuser()}` "
            "so the hub keeps running after you log out.")
    else:
        f = plist_path()
        _write(f, launchd_plist(command, path_env, extra))
        make_room()
        _bootout(tool)                                                    # a loaded agent is replaced
        _run([tool, "bootstrap", _domain(), str(f)])
        say(f"  service installed: {f}")


def _bootout(tool: str):
    """Boot the job out and wait until launchd no longer has it. `launchctl bootout` returns while the hub
    runs its clean stop, and launchd keeps the job until the hub has ended (run 41016931742): a bootstrap
    meanwhile, or an uninstall that returned then, would meet the job that was booted out."""
    target = f"{_domain()}/{LABEL}"
    _run([tool, "bootout", target], check=False)
    deadline = time.monotonic() + BOOTOUT_WAIT
    while _run([tool, "print", target], check=False).returncode == 0:
        if time.monotonic() >= deadline:
            raise ServiceError(f"launchd still has the job {BOOTOUT_WAIT} s after `launchctl bootout`; "
                               f"see `launchctl print {target}`")
        time.sleep(0.2)


def uninstall(say):
    """Disable and stop the service, remove its definition, and reload."""
    if kind() is None:
        raise ServiceError("the user service is for Linux (systemd) and macOS (launchd)")
    if not installed():
        say("  the service is not installed")
        return
    f = definition_path()
    tool = _tool()
    if kind() == "systemd":
        _run([tool, "--user", "disable", "--now", UNIT], check=False)
        f.unlink()
        _run([tool, "--user", "daemon-reload"])
    else:
        _bootout(tool)
        f.unlink()
    say("  service removed")


def control(verb: str):
    """`start`, `restart` or `stop` through the service manager. `stop` is for a hub that does not
    answer (SPEC 8.4), which is only recovered on Linux."""
    tool = _tool()
    if kind() == "systemd":
        _run([tool, "--user", verb, UNIT])
    elif verb == "stop":
        raise ServiceError(f"sheaf does not stop the launchd agent; use `launchctl bootout {_domain()}/{LABEL}`")
    else:
        _run([tool, "kickstart", *(["-k"] if verb == "restart" else []), f"{_domain()}/{LABEL}"])
