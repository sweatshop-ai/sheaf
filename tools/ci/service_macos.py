#!/usr/bin/env python3
"""CI only: the user service of SPEC 14.3 (a launchd job), installed for real on a GitHub Actions macOS runner.

It refuses anywhere else (`_ci.guard`): it loads a launchd job and starts a hub under it. The
generated plist is linted with `plutil` first; the job is loaded only where the runner has a
`gui/<uid>` domain to load it in (a notice says when it has not). Then, as service_linux.py does:
a `kill -9` is followed by a restart and an `unclean-exit` row, an upgrade stop ends in exit 75
and a restart, and `sheaf service uninstall` takes it all away. Run it with the project's
Python and `sheaf` on PATH, as ci.yml does."""
import os
import plistlib
import re
import shutil
import signal
import sys
import tempfile
from pathlib import Path

import _ci

_ci.guard("macOS")

from sheafmd import signals  # noqa: E402
from sheafmd.hub import service  # noqa: E402  (after the guard: nothing of sheaf is touched on a laptop)


def domain() -> str:
    return f"gui/{os.getuid()}"


def launchd_job() -> dict:
    """The fields of `launchctl print` this check reads: the process id and the last exit code."""
    done = _ci.quiet(["launchctl", "print", f"{domain()}/{service.LABEL}"])
    if done.returncode != 0:
        return {}
    out = {}
    pid = re.search(r"^\s*pid = (\d+)", done.stdout, flags=re.M)
    last = re.search(r"^\s*last exit code = (\S+)", done.stdout, flags=re.M)
    state = re.search(r"^\s*state = (\S+)", done.stdout, flags=re.M)
    if pid:
        out["pid"] = pid.group(1)
    if last:
        out["last_exit"] = last.group(1)
    if state:
        out["state"] = state.group(1)
    return out


def lint_the_plist(port: int, tmp: Path):
    plist = service.launchd_plist([shutil.which("sheaf")], os.environ["PATH"], {"SHEAF_PORT": str(port)})
    f = tmp / "sheaf.plist"
    f.write_bytes(plist)
    _ci.check(_ci.sh(["plutil", "-lint", str(f)]).returncode == 0, "plutil -lint accepts the generated plist")
    loaded = plistlib.loads(plist)
    _ci.check(loaded["KeepAlive"] == {"SuccessfulExit": False} and loaded["ThrottleInterval"] == 10
              and loaded["RunAtLoad"] is True and loaded["Label"] == service.LABEL, "the plist is the one of SPEC 14.3")


def hub_back(old_pid: str, seconds: int = 120):
    """The job runs another process than `old_pid`, and the hub answers."""
    def look():
        now = launchd_job()
        if now.get("state") == "running" and now.get("pid") not in (None, old_pid) and _ci.hub_answers():
            return now
    return _ci.wait_until(look, seconds=seconds, every=1)


def checks(port: int):
    plist = service.plist_path()
    _ci.say("1. install")
    _ci.check(not plist.exists(), "no plist before the install")
    _ci.check(_ci.sh(["sheaf", "service", "install"]).returncode == 0, "sheaf service install exits 0")
    _ci.check(plist.is_file(), "the plist is where the library puts it")
    _ci.check(_ci.wait_until(lambda: launchd_job().get("state") == "running", seconds=30, every=1),
              "launchd runs the job")
    _ci.check(_ci.wait_until(_ci.hub_answers, seconds=60, every=1), "the hub answers")
    status = _ci.sh(["sheaf", "status"])
    _ci.check("service  yes" in status.stdout, "the hub says it was started by the service", status.stdout)

    _ci.say("2. kill -9")
    first = launchd_job()
    signals.send(int(first["pid"]), signal.SIGKILL)
    _ci.check(hub_back(first["pid"]), "launchd restarted the hub with another process")
    _ci.check(_ci.has_row(_ci.diag(), "unclean-exit"), "the next hub wrote an unclean-exit row")

    _ci.say("3. an upgrade stop")
    before = launchd_job()
    # A newer command meets an idle hub of the service: the hub exits 75 and KeepAlive
    # {SuccessfulExit: false} starts the code that is installed.
    _ci.upgrade_command()
    _ci.check(hub_back(before["pid"]), "launchd restarted the hub after the upgrade stop")
    _ci.check(_ci.has_row(_ci.diag(), "hub-exit", reason="upgrade"), "the hub wrote hub-exit reason=upgrade")
    last = launchd_job().get("last_exit")
    if last == "75":
        _ci.say("  ok    launchctl print: last exit code = 75")
    else:
        _ci.notice(f"launchctl print says last exit code = {last}: exit 75 is shown by the hub-exit row only")

    _ci.say("4. uninstall")
    _ci.check(_ci.sh(["sheaf", "service", "uninstall"]).returncode == 0, "sheaf service uninstall exits 0")
    _ci.check(not plist.exists(), "the plist is gone")
    _ci.check(not launchd_job(), "launchd no longer knows the job")
    _ci.check(_ci.wait_until(lambda: not _ci.hub_answers(), seconds=30, every=1), "the hub is gone")


def main() -> int:
    if not shutil.which("sheaf"):
        _ci.fail("sheaf is not on PATH: the checks run the installed command")
    home = Path(tempfile.mkdtemp(prefix="sheaf-ci-service-"))
    port = _ci.free_port()
    os.environ["SHEAF_HOME"] = str(home / "sheaf-home")
    os.environ["SHEAF_PORT"] = str(port)
    try:
        lint_the_plist(port, home)
        if _ci.sh(["launchctl", "print", domain()]).returncode != 0:
            _ci.notice(f"no {domain()} launchd domain on this runner: the job was linted, not loaded")
            return 0
        try:
            checks(port)
        finally:
            if service.plist_path().exists():
                _ci.sh(["sheaf", "service", "uninstall"])
    finally:
        shutil.rmtree(home, ignore_errors=True)
    _ci.say("service checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
