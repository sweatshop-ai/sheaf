"""The suite never touches the port a real hub would use, and never leaves a hub behind."""
import os
import socket
import subprocess
import sys

import pytest

from helpers import gone, stop_hub
from sheafmd import config, paths
from sheafmd.hub import client, server

STARTED = []


def test_every_test_runs_on_a_port_of_its_own():
    assert config.port() != 27419


def test_no_variable_of_the_agent_that_runs_the_suite_reaches_a_test():
    """A suite run from inside a Claude Code session would otherwise record that session's real
    socket and command in the test's own docs.json (a Tell is one request from writing into
    it). The prefixes are the ones the hub keeps out of its own environment."""
    left = sorted(k for k in os.environ if k.startswith(client._AGENT_ENV_PREFIXES))
    assert left == []


def test_a_command_that_starts_a_hub_starts_it_on_that_port(work, sheaf, monkeypatch):
    monkeypatch.setattr("sheafmd.cli.webbrowser.open", lambda *a, **k: True)
    doc = work / "d.md"
    doc.write_text("# T\n\nHello.\n", encoding="utf-8")
    assert sheaf(doc).code == 0
    info = server.read_pid_file()
    STARTED.append(info["pid"])
    assert info["port"] == config.port() != 27419


def test_the_hub_that_test_started_was_stopped_when_it_ended():
    # Relies on the file's order: the test before this one started the hub.
    assert STARTED and gone(STARTED[0])


NOT_YET_WRITTEN = []


def test_a_hub_that_has_not_written_its_pid_file_yet_is_still_stopped_when_the_test_ends():
    """The reaper used to look for the pid file alone, and a hub that was still starting had none.
    This one is a stand-in that never writes it: whatever a test starts as `-m sheafmd hub` is
    the reaper's, by whichever path it was started."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "-m", "sheafmd", "hub"])
    NOT_YET_WRITTEN.append(p)
    assert server.read_pid_file() is None


def test_the_hub_without_a_pid_file_of_the_test_before_was_stopped():
    # Relies on the file's order, like the test above this pair.
    p = NOT_YET_WRITTEN[0]
    try:
        assert p.poll() is not None, "the reaper left a hub that had no pid file running"
    finally:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=30)


def test_the_reaper_stops_a_hub_where_there_is_no_proc_folder(monkeypatch):
    """macOS has no /proc, so the check that a pid still is a sheaf hub cannot be made there; the
    hub is stopped all the same, as the reaper always did (the check only guards against a pid
    that ended and was given to something else)."""
    import builtins

    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "-m", "sheafmd", "hub"])
    real_open = builtins.open

    def no_proc(path, *a, **k):
        if str(path).startswith("/proc/"):
            raise FileNotFoundError(path)
        return real_open(path, *a, **k)
    try:
        with monkeypatch.context() as m:
            m.setattr(builtins, "open", no_proc)
            stop_hub(p.pid)
        assert p.wait(timeout=10) is not None
    finally:
        if p.poll() is None:
            p.kill()
        p.wait(timeout=30)


# ── no test reaches the default port ─────────────────────────────────────────

def test_a_test_starts_with_a_port_of_its_own_that_every_command_resolves_to(port):
    assert port != config.DEFAULT_PORT
    assert os.environ["SHEAF_PORT"] == str(port) and config.port() == port


def test_a_process_of_sheaf_is_not_started_with_the_default_port_in_its_environment(monkeypatch):
    monkeypatch.setenv("SHEAF_PORT", str(config.DEFAULT_PORT))
    with pytest.raises(AssertionError, match="27419"):
        subprocess.Popen([sys.executable, "-m", "sheafmd", "--help"])


def test_nor_one_of_a_test_that_cleared_SHEAF_PORT(monkeypatch):
    monkeypatch.delenv("SHEAF_PORT")
    with pytest.raises(AssertionError, match="27419"):
        subprocess.run([sys.executable, "-m", "sheafmd", "--help"], capture_output=True)


def test_nor_one_that_was_given_an_environment_of_its_own_without_a_port(monkeypatch):
    env = {k: v for k, v in os.environ.items() if k != "SHEAF_PORT"}
    with pytest.raises(AssertionError, match="27419"):
        subprocess.run([sys.executable, "-m", "sheafmd", "--help"], env=env, capture_output=True)


def test_a_process_whose_port_comes_from_the_config_file_of_its_own_home_is_started(tmp_path):
    """Two accounts on one box each have `port =` in their own config.toml (tests/test_remote_box.py)."""
    home = tmp_path / "another-home"
    with pytest.MonkeyPatch.context() as m:
        m.delenv("SHEAF_HOME", raising=False)
        m.setenv("HOME", str(home))
        config_file = paths.config_file()
    config_file.parent.mkdir(parents=True)
    config_file.write_text("port = 45678\n")
    env = {k: v for k, v in os.environ.items()
           if k not in ("SHEAF_PORT", "SHEAF_HOME") and not k.startswith("XDG_")}
    env["HOME"] = str(home)
    assert subprocess.run([sys.executable, "-m", "sheafmd", "--help"], env=env, capture_output=True).returncode == 0


def test_a_process_that_is_not_sheaf_is_not_asked_about_a_port(monkeypatch):
    monkeypatch.delenv("SHEAF_PORT")
    assert subprocess.run(["true"]).returncode == 0


def test_a_connection_to_the_default_port_is_refused_before_it_is_made(monkeypatch):
    monkeypatch.delenv("SHEAF_PORT")
    with pytest.raises(AssertionError, match="27419"):
        socket.create_connection(("127.0.0.1", config.DEFAULT_PORT), timeout=1)


def test_nor_is_the_default_port_bound():
    with socket.socket() as s, pytest.raises(AssertionError, match="27419"):
        s.bind(("127.0.0.1", config.DEFAULT_PORT))


def test_any_other_port_is_reached_as_it_always_was(port):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        socket.create_connection(listener.getsockname(), timeout=5).close()
