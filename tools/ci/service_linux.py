#!/usr/bin/env python3
"""CI only: the user service of SPEC 14.3, installed for real on a GitHub Actions Linux runner.

It refuses anywhere else (`_ci.guard`): it installs a user unit and starts a hub under systemd.
Run it with the project's Python and `sheaf` on PATH, as ci.yml does. It checks, in order, what
the unit tests can only imitate: `sheaf service install` leaves the hub running as the service,
a `kill -9` is followed by a restart and an `unclean-exit` row, a stray SIGTERM ends in exit 0 and
a restart (#79), an upgrade stop (a newer command meets the idle hub) ends in exit 75 and a restart,
`sheaf stop` ends in exit 3 that systemd leaves down as a success, a `systemctl stop` while the hub's git
fetch hangs lets the hub end that git itself (`push-stopped`, never `push-failed`, #95), and `sheaf service uninstall`
takes it all away. A runner with no systemd (a container) or no systemd user session skips the checks with a
notice."""
import getpass
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

import _ci

_ci.guard("Linux")

from sheafmd import signals  # noqa: E402
from sheafmd.hub import service  # noqa: E402  (after the guard: nothing of sheaf is touched on a laptop)

FIELDS = ["ActiveState", "SubState", "MainPID", "NRestarts", "ExecMainStatus", "Result"]


def systemctl(*args: str):
    return _ci.sh(["systemctl", "--user", *args])


def show() -> dict:
    return _ci.parse_show(_ci.quiet(["systemctl", "--user", "show", service.UNIT, *[f"-p{f}" for f in FIELDS]]).stdout)


def systemd_here() -> bool:
    """systemd is what started this machine. A container has none, and `systemctl` is not
    even installed in it."""
    return bool(shutil.which("systemctl")) and Path("/run/systemd/system").is_dir()


def enable_user_session() -> bool:
    """Point this process at the user's systemd and make it linger (`sudo loginctl enable-linger`),
    which a runner needs before it has one; true when `systemctl --user` then answers."""
    run = f"/run/user/{os.getuid()}"
    os.environ["XDG_RUNTIME_DIR"] = run
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={run}/bus"
    if shutil.which("sudo") and shutil.which("loginctl"):
        _ci.sh(["sudo", "loginctl", "enable-linger", getpass.getuser()])
    return bool(_ci.wait_until(
        lambda: _ci.quiet(["systemctl", "--user", "show-environment"]).returncode == 0, seconds=30, every=1))


class Sampler(threading.Thread):
    """What systemd says about the unit, every 0.2 s: the moment between an exit and the restart
    is two seconds or more, and it holds the exit code."""

    def __init__(self):
        super().__init__(daemon=True)
        self.rows: list[dict] = []
        self._stop_now = threading.Event()

    def run(self):
        while not self._stop_now.is_set():
            self.rows.append(show())
            self._stop_now.wait(0.2)

    def finish(self):
        self._stop_now.set()
        self.join(timeout=30)

    def exits_seen(self) -> set:
        """The exit codes of the restarts: systemd shows them while the unit waits to restart."""
        return {r.get("ExecMainStatus") for r in self.rows if r.get("ActiveState") == "activating"}


def hub_back(after_restarts: int, old_pid: str, seconds: int = 90):
    """The service has restarted at least once more, with another process, and the hub answers."""
    def look():
        now = show()
        if (now.get("ActiveState") == "active" and int(now.get("NRestarts") or 0) > after_restarts
                and now.get("MainPID") not in ("0", old_pid) and _ci.hub_answers()):
            return now
    return _ci.wait_until(look, seconds=seconds, every=1)


HANG = "61.9519"                 # a sleep nothing else runs: the remote that does not answer


def hanging_root() -> Path:
    """A root that commits and pushes, whose remote's upload-pack sleeps first: the poll's fetch hangs."""
    w = Path(tempfile.mkdtemp(prefix="sheaf-ci-git-"))
    remote, root = w / "remote.git", w / "root"
    _ci.sh(["git", "init", "-q", "--bare", "-b", "main", str(remote)])
    _ci.sh(["git", "clone", "-q", str(remote), str(root)])
    for args in (["config", "user.name", "ci"], ["config", "user.email", "ci@example.com"]):
        _ci.sh(["git", "-C", str(root), *args])
    (root / ".sheaf.toml").write_text("commit = true\npush = true\n", encoding="utf-8")
    (root / "doc.md").write_text("# Doc\n\nText.\n", encoding="utf-8")
    for args in (["add", "-A"], ["commit", "-qm", "first"], ["push", "-q", "origin", "HEAD:main"],
                 ["config", "remote.origin.uploadpack", f"sleep {HANG}; git-upload-pack"]):
        _ci.sh(["git", "-C", str(root), *args])
    return root


def sleepers() -> list:
    out = []
    for d in Path("/proc").iterdir():
        try:
            if d.name.isdigit() and (d / "cmdline").read_bytes().split(b"\0")[:2] == [b"sleep", HANG.encode()]:
                out.append(int(d.name))
        except OSError:
            pass
    return out


def checks(port: int):
    unit = service.unit_path()
    _ci.say("1. install")
    _ci.check(not unit.exists(), "no unit before the install")
    done = _ci.sh(["sheaf", "service", "install"])
    _ci.check(done.returncode == 0, "sheaf service install exits 0")
    text = unit.read_text(encoding="utf-8") if unit.is_file() else ""
    _ci.check(all(f"\n{line}\n" in text for line in (
        "Restart=always", f"RestartPreventExitStatus={service.EXIT_STOPPED}",
        f"SuccessExitStatus={service.EXIT_STOPPED}", f"Environment={service.STOP_EXIT_ENV}={service.EXIT_STOPPED}",
        f"Environment=SHEAF_PORT={port}", "KillMode=mixed", f"TimeoutStopSec={service.STOP_WAIT}"))
        and "hub --started-by service" in text,
        "the unit is the one of SPEC 14.3", text)
    _ci.check(_ci.wait_until(lambda: show().get("ActiveState") == "active", seconds=30, every=1),
              "the service is active")
    _ci.check(_ci.wait_until(_ci.hub_answers, seconds=30, every=1), "the hub answers")
    status = _ci.sh(["sheaf", "status"])
    _ci.check("service  yes" in status.stdout, "the hub says it was started by the service", status.stdout)

    _ci.say("2. kill -9")
    first = show()
    sampler = Sampler()
    sampler.start()
    signals.send(int(first["MainPID"]), signal.SIGKILL)          # MainPID=0: no process, refused
    now = hub_back(int(first["NRestarts"]), first["MainPID"])
    sampler.finish()
    _ci.check(now, "the service restarted the hub with another process")
    _ci.check("9" in sampler.exits_seen(), "systemd saw the signal exit (ExecMainStatus 9) before the restart",
              str(sorted(sampler.exits_seen())))
    _ci.check(_ci.has_row(_ci.diag(), "unclean-exit"), "the next hub wrote an unclean-exit row")

    _ci.say("3. a stray SIGTERM (#79)")
    before = show()
    sampler = Sampler()
    sampler.start()
    # Not the manager's stop job: a signal from anyone else, which exits 0 and Restart=always starts again.
    signals.send(int(before["MainPID"]), signal.SIGTERM)
    now = hub_back(int(before["NRestarts"]), before["MainPID"])
    sampler.finish()
    _ci.check(now, "the service restarted the hub after a SIGTERM it did not send")
    _ci.check("0" in sampler.exits_seen(), "systemd saw exit 0 before the restart",
              str(sorted(sampler.exits_seen())))
    _ci.check(_ci.has_row(_ci.diag(), "hub-exit", reason="signal"), "the hub wrote hub-exit reason=signal")

    _ci.say("4. an upgrade stop")
    before = show()
    sampler = Sampler()
    sampler.start()
    # A newer sheaf meets an idle hub of the service (ensure_hub): the hub exits 75 and systemd starts the
    # code that is installed. That code is not newer, so this command ends by saying so.
    _ci.upgrade_command()
    now = hub_back(int(before["NRestarts"]), before["MainPID"])
    sampler.finish()
    _ci.check(now, "the service restarted the hub after the upgrade stop")
    _ci.check("75" in sampler.exits_seen(), "systemd saw exit 75 before the restart",
              str(sorted(sampler.exits_seen())))
    _ci.check(_ci.has_row(_ci.diag(), "hub-exit", reason="upgrade"), "the hub wrote hub-exit reason=upgrade")

    _ci.say("5. sheaf stop")
    before = show()
    done = _ci.sh(["sheaf", "stop"])
    _ci.check(done.returncode == 0, "sheaf stop exits 0", done.stdout + done.stderr)
    stopped = _ci.wait_until(lambda: (lambda now: now if now.get("ActiveState") == "inactive" else None)(show()),
                             seconds=30, every=0.5)
    _ci.check(stopped, "the service is inactive after sheaf stop", str(show()))
    _ci.check(stopped and stopped.get("ExecMainStatus") == str(service.EXIT_STOPPED)
              and stopped.get("Result") == "success",
              f"the hub exited {service.EXIT_STOPPED}, which systemd counts as a success", str(stopped))
    time.sleep(20)          # past the backoff: with RestartSteps the next restart here would come after about 15 s
    after = show()
    _ci.check(after.get("ActiveState") == "inactive" and after.get("NRestarts") == before.get("NRestarts")
              and not _ci.hub_answers(), "systemd left the hub stopped", str(after))
    _ci.check(_ci.has_row(_ci.diag(), "hub-exit", reason="stop"), "the hub wrote hub-exit reason=stop")

    _ci.say("6. systemctl stop while git fetches (#95)")
    systemctl("start", service.UNIT)
    _ci.check(_ci.wait_until(_ci.hub_answers, seconds=30, every=1), "the hub answers again")
    root = hanging_root()
    done = _ci.sh(["sheaf", "open", str(root / "doc.md"), "--no-browser"])
    _ci.check(done.returncode == 0, "sheaf open registers a root that commits and pushes", done.stdout + done.stderr)
    _ci.check(_ci.wait_until(sleepers, seconds=30, every=0.25), "the poll's fetch is under way and hangs")
    started = time.monotonic()
    systemctl("stop", service.UNIT)
    took = time.monotonic() - started
    _ci.check(took < service.STOP_WAIT, f"the hub stopped within TimeoutStopSec ({took:.1f} s)")
    _ci.check(not sleepers(), "nothing of the fetch is left")
    rows = _ci.diag()
    _ci.check(_ci.has_row(rows, "push-stopped", doc=root.name), "the hub wrote push-stopped for the git it ended", rows)
    _ci.check(not _ci.has_row(rows, "push-failed"), "and no push-failed", rows)

    _ci.say("7. uninstall")
    done = _ci.sh(["sheaf", "service", "uninstall"])
    _ci.check(done.returncode == 0, "sheaf service uninstall exits 0")
    _ci.check(not unit.exists(), "the unit file is gone")
    _ci.check(systemctl("is-active", service.UNIT).stdout.strip() != "active", "the service is not active")
    _ci.check(_ci.wait_until(lambda: not _ci.hub_answers(), seconds=30, every=1), "the hub is gone")


def main() -> int:
    if not shutil.which("sheaf"):
        _ci.fail("sheaf is not on PATH: the checks run the installed command")
    if not systemd_here():
        _ci.notice("no systemd on this runner (it is a container): the service checks were skipped")
        return 0
    if not enable_user_session():
        _ci.notice("no systemd user session on this runner: the service checks were skipped")
        return 0
    home = tempfile.mkdtemp(prefix="sheaf-ci-service-")
    port = _ci.free_port()
    os.environ["SHEAF_HOME"] = home
    os.environ["SHEAF_PORT"] = str(port)
    try:
        checks(port)
    finally:
        if service.unit_path().exists():
            _ci.sh(["sheaf", "service", "uninstall"])
        shutil.rmtree(home, ignore_errors=True)
    _ci.say("service checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
