#!/usr/bin/env python3
"""CI only: the user service of SPEC 14.3, installed for real on a GitHub Actions Linux runner.

It refuses anywhere else (`_ci.guard`): it installs a user unit and starts a hub under systemd.
Run it with the project's Python and `sheaf` on PATH, as ci.yml does. It checks, in order, what
the unit tests can only imitate: `sheaf service install` leaves the hub running as the service,
a `kill -9` is followed by a restart and an `unclean-exit` row, a stray SIGTERM ends in exit 0 and
a restart (#79), an upgrade stop (a newer command meets the idle hub) ends in exit 75 and a restart,
`sheaf stop` ends in exit 3 that systemd leaves down as a success, and `sheaf service uninstall`
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
        f"Environment=SHEAF_PORT={port}")) and "hub --started-by service" in text,
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
    os.kill(int(first["MainPID"]), signal.SIGKILL)
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
    os.kill(int(before["MainPID"]), signal.SIGTERM)
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
    time.sleep(6)                                         # past RestartSec: a restart would have come by now
    after = show()
    _ci.check(after.get("ActiveState") == "inactive" and after.get("NRestarts") == before.get("NRestarts")
              and not _ci.hub_answers(), "systemd left the hub stopped", str(after))
    _ci.check(_ci.has_row(_ci.diag(), "hub-exit", reason="stop"), "the hub wrote hub-exit reason=stop")

    _ci.say("6. uninstall")
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
