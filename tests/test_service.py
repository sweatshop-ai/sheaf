"""The user service (SPEC 14.3): the unit and the plist as text, `sheaf service install` and
`uninstall`, and `start` and `restart` going through the service once it is installed.

Nothing here touches the real service manager. A fake `systemctl` and `launchctl` come first on
PATH and append their arguments to a log; the home, the config and the runtime folders are this
test's own. Restart-on-crash and the backoff are systemd's and launchd's work, not sheaf's: they
are checked by the text of the unit and the plist, and on a real machine."""
import json
import os
import plistlib
import shlex
import shutil
import signal
import stat
import sys
import time

import pytest

from helpers import LATE_HUB, gone, is_stopped
from sheafmd import agent_setup
from sheafmd.hub import service
from sheafmd.hub import client as hubclient
from sheafmd.hub import server

LABEL = "io.github.sweatshop-ai.sheaf"

SPEC_UNIT = """\
[Unit]
Description=sheaf hub
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
ExecStart=/opt/sheaf/bin/sheaf hub --started-by service
Restart=always
RestartPreventExitStatus=3
SuccessExitStatus=3
RestartSec=2
RestartSteps=5
RestartMaxDelaySec=60
Environment=PATH=/opt/a:/usr/bin
Environment=SHEAF_STOP_EXIT=3

[Install]
WantedBy=default.target
"""


# ── the text ─────────────────────────────────────────────────────────────────

def test_the_unit_is_the_unit_of_the_spec():
    assert service.systemd_unit(["/opt/sheaf/bin/sheaf"], "/opt/a:/usr/bin") == SPEC_UNIT


def test_the_unit_restarts_every_exit_but_a_deliberate_stop():
    """#79: a hub that exited 0 on a stray signal stayed down under Restart=on-failure. The unit now
    restarts every exit, and the hub's code for `sheaf stop` is the one exit it does not restart, and
    counts as a success, so a stopped hub is `inactive`, not `failed`."""
    text = service.systemd_unit(["/opt/sheaf/bin/sheaf"], "/opt/a:/usr/bin")
    code = server.EXIT_STOPPED
    assert code not in (0, 1, 2, server.EXIT_UPGRADE)
    assert f"\nRestartPreventExitStatus={code}\n" in text and f"\nSuccessExitStatus={code}\n" in text
    # and tells the hub so: a unit of an older sheaf restarts a 3, so the hub exits 3 only under this one
    assert f"\nEnvironment={service.STOP_EXIT_ENV}={code}\n" in text
    assert service.STOP_EXIT_ENV not in str(plistlib.loads(service.launchd_plist(["/opt/sheaf/bin/sheaf"], "/opt/a:/usr/bin")))


def test_the_port_and_the_home_set_at_install_go_into_environment_lines():
    unit = service.systemd_unit(["/opt/sheaf/bin/sheaf"], "/usr/bin",
                                {"SHEAF_PORT": "27500", "SHEAF_HOME": "/srv/sheaf"})
    lines = unit.splitlines()
    assert "Environment=PATH=/usr/bin" in lines
    assert "Environment=SHEAF_PORT=27500" in lines and "Environment=SHEAF_HOME=/srv/sheaf" in lines
    assert lines.index("Environment=SHEAF_HOME=/srv/sheaf") < lines.index("[Install]")


def test_the_xdg_folders_a_shell_moved_go_into_the_unit_so_the_service_reads_the_same_key(monkeypatch):
    """SPEC 4.1, 14.3: a shell with its own XDG_STATE_HOME runs commands that read that `hub.key`;
    a unit without it would start a hub on another key, and every command would say that
    something else holds the port."""
    monkeypatch.setattr(service, "kind", lambda: "systemd")
    for name, value in (("XDG_STATE_HOME", "/srv/state"), ("XDG_CONFIG_HOME", "/srv/config"),
                        ("XDG_CACHE_HOME", "/srv/cache")):
        monkeypatch.setenv(name, value)
    path_env, extra = service._environment()
    lines = service.systemd_unit(["/opt/sheaf/bin/sheaf"], path_env, extra).splitlines()
    for line in ("Environment=XDG_STATE_HOME=/srv/state", "Environment=XDG_CONFIG_HOME=/srv/config",
                 "Environment=XDG_CACHE_HOME=/srv/cache"):
        assert line in lines
        assert lines.index(line) < lines.index("[Install]")


def test_an_unset_xdg_folder_is_not_written_into_the_unit(monkeypatch):
    monkeypatch.setattr(service, "kind", lambda: "systemd")
    monkeypatch.setenv("XDG_STATE_HOME", "/srv/state")
    _, extra = service._environment()
    assert {k: v for k, v in extra.items() if k.startswith("XDG_")} == {"XDG_STATE_HOME": "/srv/state"}


def test_the_plist_carries_no_xdg_folder_because_the_paths_on_macos_ignore_them(monkeypatch):
    monkeypatch.setattr(service, "kind", lambda: "launchd")
    monkeypatch.setenv("XDG_STATE_HOME", "/srv/state")
    _, extra = service._environment()
    assert [k for k in extra if k.startswith("XDG_")] == []


def test_a_path_with_a_space_or_a_percent_is_quoted_the_way_systemd_reads_it():
    unit = service.systemd_unit(["/opt/my tools/sheaf"], "/opt/a b:/usr/bin",
                                {"SHEAF_HOME": "/home/me/100%/sheaf"})
    assert 'ExecStart="/opt/my tools/sheaf" hub --started-by service' in unit
    assert 'Environment="PATH=/opt/a b:/usr/bin"' in unit
    assert "Environment=SHEAF_HOME=/home/me/100%%/sheaf" in unit
    assert "ExecStart=/opt/$$x/sheaf hub" in service.systemd_unit(["/opt/$x/sheaf"], "/usr/bin")


def test_a_command_that_is_python_dash_m_gets_each_word_in_the_unit():
    unit = service.systemd_unit(["/usr/bin/python3", "-m", "sheafmd"], "/usr/bin")
    assert "ExecStart=/usr/bin/python3 -m sheafmd hub --started-by service" in unit


def test_the_plist_is_the_plist_of_the_spec():
    data = plistlib.loads(service.launchd_plist(["/opt/sheaf/bin/sheaf"], "/opt/a:/usr/bin",
                                                {"SHEAF_PORT": "27500"}))
    assert data == {"Label": LABEL,
                    "ProgramArguments": ["/opt/sheaf/bin/sheaf", "hub", "--started-by", "service"],
                    "EnvironmentVariables": {"PATH": "/opt/a:/usr/bin", "SHEAF_PORT": "27500"},
                    "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
                    "ThrottleInterval": 10}


def script(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_the_command_is_the_script_that_runs_else_sheaf_on_the_path_else_python(monkeypatch, tmp_path):
    on_path = script(tmp_path / "bin" / "sheaf")
    monkeypatch.setenv("PATH", str(on_path.parent))
    monkeypatch.setattr(sys, "argv", ["/x/pytest"])
    assert service.sheaf_command() == [str(on_path)]
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    running = script(tmp_path / "venv" / "sheaf")
    monkeypatch.setattr(sys, "argv", [str(running), "service", "install"])
    assert service.sheaf_command() == [str(running)]
    monkeypatch.setattr(sys, "argv", ["/x/pytest"])
    assert service.sheaf_command() == [sys.executable, "-m", "sheafmd"]


def test_the_service_runs_the_sheaf_that_installed_it_not_another_one_first_on_path(monkeypatch, tmp_path):
    """SPEC 14.3: the absolute path of the sheaf executable that runs the install. With two
    installs, or after `python -m sheafmd service install`, the first `sheaf` on PATH is another."""
    other = script(tmp_path / "bin" / "sheaf")
    running = script(tmp_path / "venv" / "bin" / "sheaf")
    monkeypatch.setenv("PATH", str(other.parent))
    monkeypatch.setattr(sys, "argv", [str(running), "service", "install"])
    assert service.sheaf_command() == [str(running)]


def test_the_command_that_shows_the_state_of_the_service_is_the_managers_own(monkeypatch):
    """What `sheaf restart` points to when the service did not bring the hub up."""
    monkeypatch.setattr(service, "kind", lambda: "systemd")
    assert service.status_command() == "systemctl --user status sheaf.service"
    monkeypatch.setattr(service, "kind", lambda: "launchd")
    assert service.status_command() == f"launchctl print gui/{os.getuid()}/{LABEL}"


def test_the_command_keeps_the_path_it_was_started_by_and_does_not_follow_a_symlink(monkeypatch, tmp_path):
    """`uv tool install` puts a symlink named `sheaf` in a bin folder, to a script inside the
    tool's own environment. The command a unit or an agent's config holds is the one the person
    has on PATH (SPEC 14.3, 14.5), not the script behind it."""
    real = script(tmp_path / "tools" / "sheafmd" / "bin" / "sheaf")
    link = tmp_path / "bin" / "sheaf"
    link.parent.mkdir()
    link.symlink_to(real)
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    monkeypatch.setattr(sys, "argv", [str(link), "init", "cursor"])
    assert service.sheaf_command() == [str(link)]


# ── a fake service manager first on PATH ─────────────────────────────────────

FAKE = r'''#!/bin/bash
up=no
(exec 3<>/dev/tcp/127.0.0.1/${SHEAF_PORT:-1}) 2>/dev/null && up=yes
echo "$(basename "$0") $* [hub_up=$up]" >> "$FAKE_LOG"
case "$*" in
  *"$FAKE_FAIL"*) [ -n "$FAKE_FAIL" ] && { echo "Failed to connect to bus" >&2; exit 1; } ;;
esac
case "$*" in
  "--user restart sheaf.service"|"--user stop sheaf.service"|"kickstart -k"*)
    # A restart is a stop, then a start: the hub of FAKE_STOP_PID gets its SIGTERM and is waited for.
    # systemd sends a SIGCONT after the SIGTERM, so that a process that is stopped can end.
    if [ -n "$FAKE_STOP_PID" ]; then
      kill -TERM "$FAKE_STOP_PID" 2>/dev/null
      kill -CONT "$FAKE_STOP_PID" 2>/dev/null
      for _ in $(seq 200); do
        state=$(ps -o stat= -p "$FAKE_STOP_PID" 2>/dev/null)
        case "$state" in ""|Z*) break ;; esac          # gone, or a zombie its parent has not reaped
        sleep 0.05
      done
    fi ;;
esac
case "$*" in
  "--user start sheaf.service"|"--user restart sheaf.service"|kickstart*)
    if [ -n "$FAKE_START_HUB" ]; then
      nohup "$FAKE_START_HUB" -m sheafmd hub --started-by service >/dev/null 2>&1 &
    fi ;;
esac
exit 0
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    d = tmp_path / "fakebin"
    d.mkdir()
    for name in ("systemctl", "launchctl"):
        f = d / name
        f.write_text(FAKE)
        f.chmod(0o755)
    log = tmp_path / "calls.log"
    log.write_text("")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_FAIL", "")
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ['PATH']}")
    # The guard: whatever runs `systemctl` in these tests is the fake and never the real one.
    assert shutil.which("systemctl") == str(d / "systemctl")
    assert shutil.which("launchctl") == str(d / "launchctl")

    class Fake:
        def calls(self):
            return [ln.rsplit(" [hub_up=", 1)[0] for ln in log.read_text().splitlines()]

        def lines(self):
            return log.read_text().splitlines()
    return Fake()


@pytest.fixture
def unit_file(tmp_path):
    return tmp_path / "home" / ".config" / "systemd" / "user" / "sheaf.service"


@pytest.fixture
def plist_file(tmp_path):
    return tmp_path / "home" / "Library" / "LaunchAgents" / f"{LABEL}.plist"


@pytest.fixture
def linux(monkeypatch):
    """The systemd branch, whatever machine runs the suite: the same seam as `macos`."""
    monkeypatch.setattr(service, "kind", lambda: "systemd")


@pytest.fixture
def macos(monkeypatch):
    monkeypatch.setattr(service, "kind", lambda: "launchd")


# ── install and uninstall on Linux ───────────────────────────────────────────

def test_install_writes_the_unit_reloads_and_enables_it_now(sheaf, linux, fake, unit_file, port):
    r = sheaf("service", "install")
    assert r.code == 0, r.err
    assert unit_file.is_file() and stat.S_IMODE(unit_file.stat().st_mode) == 0o644
    text = unit_file.read_text()
    assert text.startswith("[Unit]\nDescription=sheaf hub\n") and "Restart=always" in text
    assert f"Environment=SHEAF_PORT={port}" in text            # the port set at install goes in
    assert f"Environment=PATH={os.environ['PATH']}" in text    # the PATH of the shell that ran it
    assert fake.calls() == ["systemctl --user daemon-reload",
                            "systemctl --user enable --now sheaf.service"]
    assert str(unit_file) in r.out
    assert "loginctl enable-linger" in r.out and "keeps running after you log out" in r.out


def test_install_over_a_unit_that_differs_says_the_running_hub_takes_it_at_its_next_start(
        sheaf, linux, fake, unit_file):
    """#79: a hub the service runs keeps the environment it started with, so under the new unit its
    `sheaf stop` would exit 0 and be restarted until it starts again. Install says how to apply it."""
    unit_file.parent.mkdir(parents=True)
    unit_file.write_text(SPEC_UNIT.replace("Restart=always\nRestartPreventExitStatus=3\nSuccessExitStatus=3\n",
                                           "Restart=on-failure\n"))
    r = sheaf("service", "install")
    assert r.code == 0, r.err
    assert "RestartPreventExitStatus=3" in unit_file.read_text()
    assert "run `sheaf restart`" in r.out
    again = sheaf("service", "install")                        # the same unit: nothing to apply
    assert again.code == 0 and "sheaf restart" not in again.out


def test_a_first_install_says_nothing_about_a_restart(sheaf, linux, fake, unit_file):
    r = sheaf("service", "install")
    assert r.code == 0 and "sheaf restart" not in r.out


def test_install_honours_xdg_config_home(sheaf, linux, fake, tmp_path, monkeypatch):
    cfg = tmp_path / "xdg-config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    assert sheaf("service", "install").code == 0
    assert (cfg / "systemd" / "user" / "sheaf.service").is_file()


def test_a_second_install_changes_nothing_and_runs_the_same_commands(sheaf, linux, fake, unit_file):
    sheaf("service", "install")
    first = unit_file.read_text()
    r = sheaf("service", "install")
    assert r.code == 0 and unit_file.read_text() == first
    assert fake.calls() == ["systemctl --user daemon-reload", "systemctl --user enable --now sheaf.service"] * 2


def test_install_makes_room_first_by_stopping_a_hub_a_command_started(sheaf, linux, fake, unit_file, port):
    sheaf("start")
    assert server.read_pid_file()["service"] is False
    r = sheaf("service", "install")
    assert r.code == 0 and "stopping the hub that is running" in r.out
    enable = next(ln for ln in fake.lines() if "enable --now" in ln)
    assert enable.endswith("[hub_up=no]")                 # the port was free when the service started
    assert hubclient.client().challenge() is None


def test_install_leaves_a_hub_the_service_already_runs_alone(
        sheaf, linux, fake, unit_file, port, procs_of_service):
    got = hubclient.client().challenge()
    assert got["service"] is True
    r = sheaf("service", "install")
    assert r.code == 0 and "stopping the hub" not in r.out
    assert hubclient.client().challenge()["boot"] == got["boot"]


@pytest.fixture
def procs_of_service(port):
    import subprocess
    import time
    p = subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", "service"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(200):
        if hubclient.client().challenge():
            break
        time.sleep(0.05)
    yield p
    p.terminate()
    p.wait(timeout=30)
    if (server.read_pid_file() or {}).get("pid") == p.pid:      # not the file of a hub that came after it
        server.pid_file().unlink(missing_ok=True)


def test_uninstall_disables_removes_the_file_and_reloads(sheaf, linux, fake, unit_file):
    sheaf("service", "install")
    r = sheaf("service", "uninstall")
    assert r.code == 0 and not unit_file.exists()
    assert fake.calls()[2:] == ["systemctl --user disable --now sheaf.service",
                                "systemctl --user daemon-reload"]


def test_uninstall_with_nothing_installed_says_so_and_runs_nothing(sheaf, linux, fake, unit_file):
    r = sheaf("service", "uninstall")
    assert r.code == 0 and "not installed" in r.out and fake.calls() == []


def test_uninstall_refuses_when_the_unit_file_is_behind_a_folder_that_may_not_be_entered(
        sheaf, linux, fake, unit_file, closed):
    """On 3.14 it said "the service is not installed" and left the service enabled."""
    sheaf("service", "install")
    before = fake.calls()
    closed(unit_file.parent)
    r = sheaf("service", "uninstall")
    assert r.code == 1 and r.err.strip() == (
        f"sheaf: cannot tell whether the user service is installed: {unit_file}: Permission denied")
    assert "not installed" not in r.out and fake.calls() == before


def test_a_machine_without_systemctl_gets_a_clear_message_and_no_file(
        sheaf, linux, unit_file, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    r = sheaf("service", "install")
    assert r.code == 1 and "systemctl" in r.err and "systemd" in r.err
    assert not unit_file.exists()


def test_a_systemctl_that_fails_is_reported_with_its_own_words(sheaf, linux, fake, monkeypatch, unit_file):
    monkeypatch.setenv("FAKE_FAIL", "enable")
    r = sheaf("service", "install")
    assert r.code == 1
    assert "systemctl --user enable --now sheaf.service" in r.err and "Failed to connect to bus" in r.err


def test_the_service_commands_have_a_usage(sheaf, fake):
    assert sheaf("service").code == 2
    assert sheaf("service", "frobnicate").code == 2
    assert fake.calls() == []


# ── install and uninstall on macOS (the plist is what is tested) ─────────────

def test_install_on_macos_writes_the_plist_and_bootstraps_it(sheaf, fake, macos, plist_file, port):
    r = sheaf("service", "install")
    assert r.code == 0, r.err
    assert stat.S_IMODE(plist_file.stat().st_mode) == 0o644
    data = plistlib.loads(plist_file.read_bytes())
    assert data["Label"] == LABEL and data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["ProgramArguments"][-3:] == ["hub", "--started-by", "service"]
    assert data["EnvironmentVariables"]["SHEAF_PORT"] == str(port)
    uid = os.getuid()
    assert fake.calls() == [f"launchctl bootout gui/{uid}/{LABEL}",
                            f"launchctl bootstrap gui/{uid} {plist_file}"]
    assert "enable-linger" not in r.out                       # a Linux remark


def test_uninstall_on_macos_boots_it_out_and_removes_the_plist(sheaf, fake, macos, plist_file):
    sheaf("service", "install")
    r = sheaf("service", "uninstall")
    assert r.code == 0 and not plist_file.exists()
    assert fake.calls()[-1] == f"launchctl bootout gui/{os.getuid()}/{LABEL}"


def test_a_second_install_on_macos_boots_out_and_bootstraps_again(sheaf, fake, macos, plist_file):
    sheaf("service", "install")
    first = plist_file.read_bytes()
    r = sheaf("service", "install")
    assert r.code == 0 and plist_file.read_bytes() == first
    uid = os.getuid()
    assert fake.calls() == [f"launchctl bootout gui/{uid}/{LABEL}",
                            f"launchctl bootstrap gui/{uid} {plist_file}"] * 2


def test_install_on_macos_makes_room_before_the_agent_is_loaded(sheaf, fake, macos, plist_file, port):
    sheaf("start")
    assert server.read_pid_file()["service"] is False
    r = sheaf("service", "install")
    assert r.code == 0 and "stopping the hub that is running" in r.out
    bootstrap = next(ln for ln in fake.lines() if " bootstrap " in ln)
    assert bootstrap.endswith("[hub_up=no]")                  # the port was free when launchd started it
    assert hubclient.client().challenge() is None


def test_a_machine_without_launchctl_gets_a_clear_message_and_no_file(
        sheaf, macos, plist_file, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    r = sheaf("service", "install")
    assert r.code == 1 and "launchctl" in r.err and "launchd" in r.err
    assert not plist_file.exists()


def test_a_launchctl_that_fails_is_reported_with_its_own_words(sheaf, fake, macos, monkeypatch, plist_file):
    monkeypatch.setenv("FAKE_FAIL", "bootstrap")
    r = sheaf("service", "install")
    assert r.code == 1
    assert f"launchctl bootstrap gui/{os.getuid()} {plist_file}" in r.err and "Failed to connect to bus" in r.err


def test_a_system_that_is_neither_linux_nor_macos_is_refused(sheaf, monkeypatch):
    monkeypatch.setattr(service, "kind", lambda: None)
    r = sheaf("service", "install")
    assert r.code == 1 and "Linux" in r.err and "macOS" in r.err


# ── a sheaf run from a temporary copy (uvx, pipx run) installs no service ────
#
# `uvx --from <source> sheaf service install` runs `<uv cache>/archive-v0/<hash>/bin/sheaf`, and
# `pipx run --spec <source> sheaf service install` runs `<pipx cache>/<15 hex>/bin/sheaf` (the venv holds `pipx_metadata.json`, and
# `pipx run` deletes a cached venv after some days). A unit that pointed there would fail once the copy is gone, long after the install.

UVX_SHEAF = "/home/u/.cache/uv/archive-v0/9YP2VgzG0HljE9FE5UbQP/bin/sheaf"


def pipx_venv(root, name, *, metadata=True):
    """A venv laid out as pipx lays one out: `bin/sheaf`, and `pipx_metadata.json` beside `bin`."""
    venv = root / name
    sheaf_script = script(venv / "bin" / "sheaf")
    if metadata:
        (venv / "pipx_metadata.json").write_text('{"pipx_metadata_version": "0.5"}\n')
    return sheaf_script


def run_as(monkeypatch, path):
    monkeypatch.setattr(sys, "argv", [str(path), "service", "install"])


@pytest.fixture
def no_record(monkeypatch):
    """No `direct_url.json` for this sheaf: the line to run is `uv tool install sheafmd`."""
    monkeypatch.setattr(agent_setup, "installed_from", lambda: None)


def refused_from_a_cache(r, fake, path, tool):
    assert r.code == 1 and r.out == ""
    assert f"temporary copy in {tool}'s cache ({path})" in r.err
    assert "uv tool install sheafmd" in r.err and "sheaf service install" in r.err
    assert fake.calls() == []                                   # the manager was never asked


def test_install_from_uvx_writes_no_unit_and_says_how_to_install_sheaf(
        sheaf, linux, fake, unit_file, monkeypatch, no_record):
    monkeypatch.setattr(service, "sheaf_command", lambda: [UVX_SHEAF])
    r = sheaf("service", "install")
    refused_from_a_cache(r, fake, UVX_SHEAF, "uv")
    assert not unit_file.exists() and not unit_file.parent.exists()


def test_install_from_uvx_with_an_unreadable_record_says_the_fallback_line_not_a_traceback(
        sheaf, linux, fake, unit_file, monkeypatch):
    class Unreadable:
        def read_text(self, name):
            raise OSError(5, "Input/output error")
    monkeypatch.setattr(service, "sheaf_command", lambda: [UVX_SHEAF])
    monkeypatch.setattr(agent_setup.metadata, "distribution", lambda name: Unreadable())
    r = sheaf("service", "install")
    refused_from_a_cache(r, fake, UVX_SHEAF, "uv")
    assert not unit_file.exists()


def test_install_from_uvx_of_a_signed_archive_url_prints_no_token_and_says_it_left_the_query_out(
        sheaf, linux, fake, unit_file, monkeypatch):
    monkeypatch.setattr(service, "sheaf_command", lambda: [UVX_SHEAF])
    monkeypatch.setattr(agent_setup, "installed_from", lambda: json.dumps({
        "url": "https://files.example.invalid/dl/sheafmd-1.0.0.tar.gz?token=tok-77ac01d2",
        "archive_info": {}, "subdirectory": "pkg"}))
    r = sheaf("service", "install")
    assert r.code == 1 and "tok-77ac01d2" not in r.err
    assert "'sheafmd @ https://files.example.invalid/dl/sheafmd-1.0.0.tar.gz#subdirectory=pkg'" in r.err
    assert "the URL had a query or a fragment, which is left out" in r.err
    assert fake.calls() == []


def test_install_from_pipx_run_writes_no_unit_and_says_how_to_install_sheaf(
        sheaf, linux, fake, unit_file, monkeypatch, tmp_path, no_record):
    cache = tmp_path / "pipx" / ".cache"
    running = pipx_venv(cache, "2207f8a391f550f")
    (cache / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    run_as(monkeypatch, running)
    r = sheaf("service", "install")
    refused_from_a_cache(r, fake, running, "pipx")
    assert "14 days" in r.err
    assert not unit_file.exists()


def test_install_from_pipx_run_on_macos_writes_no_plist(
        sheaf, macos, fake, plist_file, monkeypatch, tmp_path, no_record):
    running = pipx_venv(tmp_path / ".local" / "pipx" / ".cache", "0f1e2d3c4b5a697")
    run_as(monkeypatch, running)
    r = sheaf("service", "install")
    refused_from_a_cache(r, fake, running, "pipx")
    assert not plist_file.exists()


def test_install_from_a_link_into_pipx_run_is_the_same(sheaf, linux, fake, unit_file, monkeypatch, tmp_path):
    real = pipx_venv(tmp_path / "pipx" / ".cache", "2207f8a391f550f")
    link = tmp_path / "bin" / "sheaf"
    link.parent.mkdir()
    link.symlink_to(real)
    run_as(monkeypatch, link)
    r = sheaf("service", "install")
    assert r.code == 1 and "pipx's cache" in r.err and not unit_file.exists()


@pytest.mark.parametrize("where", ["pipx install", "uv project", "hash without pipx", "checkout"])
def test_a_sheaf_that_is_installed_installs_the_service_as_before(
        sheaf, linux, fake, unit_file, port, monkeypatch, tmp_path, where):
    """`pipx install` keeps its venv for good, under `venvs/<package>`, with the same metadata file;
    uv writes a CACHEDIR.TAG into a project's `.venv`, which is a developer's own and stays."""
    if where == "pipx install":
        running = pipx_venv(tmp_path / "pipx" / "venvs", "sheafmd")
    elif where == "uv project":
        running = script(tmp_path / "work" / "sheaf" / ".venv" / "bin" / "sheaf")
        (running.parent.parent / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n")
    elif where == "hash without pipx":
        running = pipx_venv(tmp_path / "builds", "2207f8a391f550f", metadata=False)
    else:
        running = script(tmp_path / "work" / "2207f8a391f550f" / ".venv" / "bin" / "sheaf")
    run_as(monkeypatch, running)
    r = sheaf("service", "install")
    assert r.code == 0, r.err
    assert f"ExecStart={running} hub --started-by service" in unit_file.read_text()


def test_a_system_that_is_neither_linux_nor_macos_is_refused_as_such_from_uvx_too(sheaf, monkeypatch):
    monkeypatch.setattr(service, "kind", lambda: None)
    monkeypatch.setattr(service, "sheaf_command", lambda: [UVX_SHEAF])
    r = sheaf("service", "install")
    assert r.code == 1 and "Linux" in r.err and "macOS" in r.err and "cache" not in r.err


@pytest.mark.parametrize("platform, manager", [("systemd", "systemctl"), ("launchd", "launchctl")])
def test_a_temporary_copy_on_a_machine_without_a_service_manager_is_told_that_first(
        sheaf, monkeypatch, tmp_path, platform, manager):
    """Installing sheaf for good would not help there, so the advice to do it comes second: the
    person is not sent to install sheaf only to meet the manager's absence on the next try."""
    monkeypatch.setattr(service, "kind", lambda: platform)
    monkeypatch.setattr(service, "sheaf_command", lambda: [UVX_SHEAF])
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    r = sheaf("service", "install")
    assert r.code == 1 and f"{manager} was not found on PATH" in r.err
    assert "temporary copy" not in r.err and "uv tool install" not in r.err


def test_which_temporary_copy_a_command_runs_from(tmp_path):
    run = pipx_venv(tmp_path / "pipx" / ".cache", "2207f8a391f550f")
    assert service.runs_from_a_cache([UVX_SHEAF]) == "uv"
    assert service.runs_from_a_cache([str(run)]) == "pipx"
    assert service.runs_from_a_cache([str(run.parent / "python"), "-m", "sheafmd"]) == "pipx"
    assert service.runs_from_a_cache([str(pipx_venv(tmp_path / "pipx" / "venvs", "sheafmd"))]) is None
    assert service.runs_from_a_cache(["/home/u/work/.venv/bin/sheaf"]) is None


# ── start and restart go through the service once it is installed ────────────

def test_start_goes_through_the_service_when_it_is_installed(sheaf, linux, fake, unit_file, port, monkeypatch):
    sheaf("service", "install")
    monkeypatch.setenv("FAKE_START_HUB", sys.executable)
    r = sheaf("start")
    assert r.code == 0 and f"hub started on 127.0.0.1:{port}" in r.out
    assert fake.calls()[-1] == "systemctl --user start sheaf.service"
    assert server.read_pid_file()["service"] is True            # the service's hub, not a detached one
    assert "service  yes" in sheaf("status").out


def test_start_through_the_service_waits_for_its_hub_while_it_listens_and_does_not_answer_yet(
        sheaf, linux, fake, unit_file, port, tmp_path, monkeypatch):
    """The service's hub listens from its bind on and answers once it serves; the wait for it took that
    silence for a hub that does not answer."""
    sheaf("service", "install")
    late = tmp_path / "late-python"
    late.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} -c {shlex.quote(LATE_HUB)} "$@"\n')
    late.chmod(0o755)
    monkeypatch.setenv("FAKE_START_HUB", str(late))
    monkeypatch.setenv("LATE_BY", "2")
    monkeypatch.setattr(hubclient, "TIMEOUT", 0.5)
    r = sheaf("start")
    assert r.code == 0, r.err
    assert f"hub started on 127.0.0.1:{port}" in r.out and server.read_pid_file()["service"] is True


def test_start_with_a_hub_already_running_does_not_ask_the_service(
        sheaf, linux, fake, unit_file, procs_of_service):
    sheaf("service", "install")
    before = len(fake.calls())
    r = sheaf("start")
    assert r.code == 0 and "hub running" in r.out and len(fake.calls()) == before


def test_start_with_a_hub_already_running_says_so_even_when_the_unit_file_cannot_be_looked_at(
        sheaf, linux, fake, unit_file, procs_of_service, closed):
    """`start` with a hub already running asks nothing of the service, so it needs no answer about it."""
    sheaf("service", "install")
    before = fake.calls()
    closed(unit_file.parent)
    r = sheaf("start")
    assert r.code == 0 and "hub running" in r.out and fake.calls() == before


def test_restart_goes_through_the_service_when_it_is_installed(sheaf, linux, fake, unit_file, port, monkeypatch):
    sheaf("service", "install")
    monkeypatch.setenv("FAKE_START_HUB", sys.executable)
    r = sheaf("restart")
    assert r.code == 0 and f"hub started on 127.0.0.1:{port}" in r.out
    assert fake.calls()[-1] == "systemctl --user restart sheaf.service"


@pytest.fixture
def command_hub(port):
    """A factory for a hub that a command started (not the service): it holds the port."""
    import subprocess
    import time
    made = []

    def start():
        p = subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", "cli"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        made.append(p)
        for _ in range(200):
            try:
                if hubclient.client().challenge():
                    break
            except hubclient.HubSilent:
                pass                                # it listens and does not answer yet: it is starting
            time.sleep(0.05)
        return p
    yield start
    for p in made:
        if p.poll() is None:
            p.terminate()
        p.wait(timeout=30)


def hub_exits():
    from sheafmd import diagnostics
    return [(r["boot"], r["reason"]) for r in diagnostics.read()
            if r["source"] == "hub" and r["kind"] == "hub-exit"]


def test_restart_through_the_service_makes_room_for_a_hub_a_command_started(
        sheaf, linux, fake, unit_file, port, command_hub, monkeypatch):
    sheaf("service", "install")                                 # installed, and no hub yet
    started = command_hub()
    old = hubclient.client().challenge()
    assert old["service"] is False
    monkeypatch.setenv("FAKE_START_HUB", sys.executable)
    r = sheaf("restart")
    assert r.code == 0, r.err
    assert "stopping the hub that is running" in r.out
    got = hubclient.client().challenge()
    assert got["service"] is True and got["boot"] != old["boot"]     # the service's hub holds the port
    assert started.wait(timeout=30) == 0
    assert hub_exits() == [(old["boot"], "upgrade")]           # tabs ride through, as on the direct path
    assert fake.calls()[-1] == "systemctl --user restart sheaf.service"


RESTARTED = []


def test_restart_through_the_service_tells_the_hub_its_reason_before_the_manager_stops_it(
        sheaf, linux, fake, unit_file, port, procs_of_service, monkeypatch):
    sheaf("service", "install")                                 # the hub it runs is left alone
    old = hubclient.client().challenge()
    assert old["service"] is True
    monkeypatch.setenv("FAKE_START_HUB", sys.executable)
    monkeypatch.setenv("FAKE_STOP_PID", str(procs_of_service.pid))
    r = sheaf("restart")
    assert r.code == 0, r.err
    assert hub_exits() == [(old["boot"], "upgrade")]           # not "signal": the row of the direct path
    assert procs_of_service.wait(timeout=30) == 0               # a restart the manager asked for, not a failure
    RESTARTED.append(server.read_pid_file()["pid"])             # the hub the manager started: not the test's child


def test_the_hub_the_manager_started_in_the_test_before_was_stopped_when_it_ended():
    """The pid file of that hub was deleted by a fixture that meant the old hub's, and the
    reaper looks for the pid file (a fake manager's hub is no child of the test)."""
    assert RESTARTED and gone(RESTARTED[0])


def test_a_stop_signal_that_nobody_announced_is_still_a_signal(
        sheaf, fake, unit_file, port, procs_of_service):
    old = hubclient.client().challenge()
    procs_of_service.terminate()
    procs_of_service.wait(timeout=30)
    assert hub_exits() == [(old["boot"], "signal")]


def test_a_restart_the_manager_refused_leaves_the_next_stop_signal_a_signal(
        sheaf, linux, fake, unit_file, port, procs_of_service, monkeypatch):
    """`sheaf restart` told the hub, then `systemctl restart` failed: a logout or a `systemctl stop`
    in the 30 s after is not that restart. It must not be written down as an upgrade, nor shown to
    the tabs as one (8.4)."""
    sheaf("service", "install")                                 # the hub it runs is left alone
    old = hubclient.client().challenge()
    assert old["service"] is True
    monkeypatch.setenv("FAKE_FAIL", "restart")
    r = sheaf("restart")
    assert r.code == 1 and "systemctl --user restart sheaf.service" in r.err
    assert "Failed to connect to bus" in r.err
    assert hubclient.client().challenge()["boot"] == old["boot"]      # the manager did nothing to it
    procs_of_service.terminate()                                # the logout, well within the 30 s
    assert procs_of_service.wait(timeout=30) == 0
    assert hub_exits() == [(old["boot"], "signal")]


def test_start_and_restart_on_macos_kickstart_the_job(sheaf, fake, macos, plist_file, port, monkeypatch):
    sheaf("service", "install")
    monkeypatch.setenv("FAKE_START_HUB", sys.executable)
    uid = os.getuid()
    sheaf("start")
    assert fake.calls()[-1] == f"launchctl kickstart gui/{uid}/{LABEL}"
    sheaf("restart")
    assert fake.calls()[-1] == f"launchctl kickstart -k gui/{uid}/{LABEL}"


def test_a_service_that_brings_no_hub_up_is_said_with_where_to_look(sheaf, linux, fake, unit_file, monkeypatch):
    sheaf("service", "install")
    monkeypatch.setattr(hubclient, "START_WAIT", 0.5)
    r = sheaf("start")                                          # the fake starts nothing
    assert r.code == 1 and "sheaf diag" in r.err and "systemctl --user status sheaf.service" in r.err


def test_a_service_that_brings_no_hub_up_on_macos_is_said_with_where_to_look(
        sheaf, fake, macos, plist_file, monkeypatch):
    sheaf("service", "install")
    monkeypatch.setattr(hubclient, "START_WAIT", 0.5)
    r = sheaf("start")                                          # the fake starts nothing
    assert r.code == 1 and "sheaf diag" in r.err and f"launchctl print gui/{os.getuid()}/{LABEL}" in r.err


@pytest.mark.parametrize("command", ["start", "restart"])
def test_start_and_restart_refuse_when_the_unit_file_is_behind_a_folder_that_may_not_be_entered(
        sheaf, linux, fake, unit_file, port, closed, command):
    """Python 3.14's `is_file` says False there, and the command went around the service: a hub of
    its own, detached; 3.13's raises, a traceback. Nobody can tell whether the service is installed."""
    sheaf("service", "install")
    before = fake.calls()
    closed(unit_file.parent)
    r = sheaf(command)
    assert r.code == 1 and r.err.strip() == (
        f"sheaf: cannot tell whether the user service is installed: {unit_file}: Permission denied")
    assert fake.calls() == before and hubclient.client().challenge() is None


def test_without_the_service_start_and_restart_are_what_they_were(sheaf, fake, port):
    assert sheaf("start").code == 0 and server.read_pid_file()["service"] is False
    assert sheaf("restart").code == 0
    assert fake.calls() == []


# ── a hub that holds its port and does not answer (8.4, 9.4) ─────────────────

@pytest.fixture
def stop_it(request):
    """`stop_it(pid)`: SIGSTOP, and wait until the process is stopped: the hub of the test holds its port
    and answers nothing. At the end of the test it is continued, so that the fixture that started it can
    stop it (a stopped process runs no SIGTERM handler)."""
    def stop(pid):
        os.kill(pid, signal.SIGSTOP)

        def go_on():
            try:
                os.kill(pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        request.node.addfinalizer(go_on)          # the test's own, not this fixture's: it runs before any fixture ends
        for _ in range(200):
            if is_stopped(pid):
                return
            time.sleep(0.05)
        raise AssertionError("the process did not stop")
    return stop


@pytest.fixture
def quick_silence(monkeypatch):
    monkeypatch.setattr(hubclient, "TIMEOUT", 0.5)


def test_restart_asks_the_manager_for_a_silent_hub_the_service_runs_and_never_signals_it(
        stop_it, sheaf, linux, fake, unit_file, port, procs_of_service, quick_silence, sent, monkeypatch):
    """A supervised process that is killed behind the manager's back is started again by the manager on
    its own, or left a unit that thinks it is up: the manager is asked, and it signals (as systemd does:
    SIGTERM, then SIGCONT, so that a stopped process can end)."""
    sheaf("service", "install")                                 # the hub it runs is left alone
    old = server.read_pid_file()
    assert old["service"] is True
    stop_it(procs_of_service.pid)
    monkeypatch.setenv("FAKE_START_HUB", sys.executable)
    monkeypatch.setenv("FAKE_STOP_PID", str(procs_of_service.pid))
    r = sheaf("restart")
    assert r.code == 0, r.err
    assert sent == []                                           # nothing was sent from here
    assert (f"the sheaf hub (pid {old['pid']}) on 127.0.0.1:{port} did not answer; "
            "asking the service to restart it") in r.out
    assert fake.calls()[-1] == "systemctl --user restart sheaf.service"
    assert fake.calls().count("systemctl --user restart sheaf.service") == 1       # asked once
    assert procs_of_service.wait(timeout=30) == 0               # it went on the manager's SIGTERM
    got = hubclient.client().challenge()
    assert got["service"] is True and got["boot"] != old["boot"]
    assert f"hub started on 127.0.0.1:{port}" in r.out


def test_restart_stops_a_silent_hub_a_command_started_and_then_asks_the_manager(
        stop_it, sheaf, linux, fake, unit_file, port, command_hub, quick_silence, sent, monkeypatch):
    sheaf("service", "install")                                 # installed, and no hub yet
    started = command_hub()
    assert server.read_pid_file()["service"] is False
    stop_it(started.pid)
    monkeypatch.setenv("FAKE_START_HUB", sys.executable)
    r = sheaf("restart")
    assert r.code == 0, r.err
    assert [s for _, _, s, _ in sent] == [signal.SIGTERM, signal.SIGCONT]      # ours to stop: no manager runs it
    assert f"stopped the sheaf hub (pid {started.pid}) that held 127.0.0.1:{port} and did not answer" in r.out
    assert started.wait(timeout=30) == 0
    assert fake.calls()[-1] == "systemctl --user restart sheaf.service"
    assert hubclient.client().challenge()["service"] is True


def test_stop_asks_the_manager_to_stop_a_silent_hub_the_service_runs(
        stop_it, sheaf, linux, fake, unit_file, port, procs_of_service, quick_silence, sent, monkeypatch):
    sheaf("service", "install")
    pid = procs_of_service.pid
    stop_it(pid)
    monkeypatch.setenv("FAKE_STOP_PID", str(pid))
    r = sheaf("stop")
    assert r.code == 0, r.err
    assert sent == []
    assert f"the sheaf hub (pid {pid}) on 127.0.0.1:{port} did not answer; asking the service to stop it" in r.out
    assert fake.calls()[-1] == "systemctl --user stop sheaf.service"
    assert r.out.rstrip().endswith("hub stopped")
    assert procs_of_service.wait(timeout=30) == 0 and hubclient.client().challenge() is None


def test_stop_does_not_say_stopped_while_the_hub_still_holds_the_port(
        stop_it, sheaf, linux, fake, unit_file, port, procs_of_service, quick_silence, sent, monkeypatch):
    """The manager said yes and ended nothing (the fake's FAKE_STOP_PID is not set): a hub that answers
    nothing is not a closed port, and `stop` must not report it as one."""
    sheaf("service", "install")
    stop_it(procs_of_service.pid)
    monkeypatch.setattr(hubclient, "STOP_WAIT", 0.5)
    r = sheaf("stop")
    assert r.code == 1 and "hub stopped" not in r.out
    assert f"127.0.0.1:{port} is still held" in r.err
    assert fake.calls()[-1] == "systemctl --user stop sheaf.service" and sent == []


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_silent_hub_the_service_runs_is_left_alone_when_no_service_is_installed(
        stop_it, sheaf, linux, fake, unit_file, port, procs_of_service, quick_silence, sent, command):
    """The pid file says the service started it, and there is no manager to ask: it is not ours to kill."""
    assert not unit_file.exists()
    stop_it(procs_of_service.pid)
    r = sheaf(command)
    assert r.code == 1 and r.err.strip() == (
        f"! the sheaf hub on 127.0.0.1:{port} did not answer within 0.5 s, and `sheaf {command}` stopped nothing: "
        f"pid {procs_of_service.pid} is the service's hub and the service is not installed")
    assert sent == [] and fake.calls() == []
    assert is_stopped(procs_of_service.pid)


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_silent_hub_the_service_runs_is_left_alone_when_its_unit_file_cannot_be_looked_at(
        stop_it, sheaf, linux, fake, unit_file, port, procs_of_service, quick_silence, sent, closed, command):
    """On 3.14 `stop` said "the service is not installed", which it is."""
    sheaf("service", "install")
    before = fake.calls()
    stop_it(procs_of_service.pid)
    closed(unit_file.parent)
    r = sheaf(command)
    assert r.code == 1
    assert f"cannot tell whether the user service is installed: {unit_file}: Permission denied" in r.err
    assert "not installed" not in r.err
    assert sent == [] and fake.calls() == before
    assert is_stopped(procs_of_service.pid)


def test_a_service_manager_that_fails_to_restart_a_silent_hub_is_reported_in_its_words(
        stop_it, sheaf, linux, fake, unit_file, port, procs_of_service, quick_silence, sent, monkeypatch):
    sheaf("service", "install")
    stop_it(procs_of_service.pid)
    monkeypatch.setenv("FAKE_FAIL", "restart")
    r = sheaf("restart")
    assert r.code == 1 and "systemctl --user restart sheaf.service" in r.err and "Failed to connect" in r.err
    assert sent == []


def test_the_service_is_never_asked_to_stop_on_macos(fake, macos):
    """Recovery needs /proc, which macOS has not, so this is not reachable there; `control` still says no
    rather than kickstart an agent that was meant to be stopped."""
    with pytest.raises(service.ServiceError):
        service.control("stop")
    assert fake.calls() == []
