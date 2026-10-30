"""No signal reaches a pid that is not one process of ours (sheaf#85).

`kill(-1, sig)` signals every process the user may signal, `kill(0, sig)` the caller's own group and
`kill(1, sig)` init. On macOS, which has no /proc, the teardown of every test once sent SIGTERM to
whatever pid the test had written into `hub.pid`: `test_a_pid_that_is_not_one_process_is_never_signalled[-1-...]`
wrote -1, and the runner received SIGTERM with every other process of its user.

`os.kill`, `os.killpg` and `os.waitpid` are replaced here before anything is called, so none of these
tests can signal or reap anything real, whatever the code under test does."""
import ast
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

import helpers
from sheafmd import signals

NOT_ONE_PROCESS = [-1, 0, 1, -4242, 2 ** 40, True, False, None, 1.0, "4242", [4242]]
KILL, WAITPID = os.kill, os.waitpid      # the real ones, for the children of these tests


@pytest.fixture
def calls(monkeypatch):
    """Every kill and killpg that was asked for, and every waitpid of anything but one child, as ("kill",
    pid, sig) and so on. Nothing is sent and nothing is reaped. A waitpid of one pid is passed on: it reaps
    only a child of this process (`subprocess` reaps its own that way), never another's."""
    log = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: log.append(("kill", pid, sig)))
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: log.append(("killpg", pgid, sig)))

    def waitpid(pid, options):
        if type(pid) is int and pid > 0:
            return WAITPID(pid, options)
        log.append(("waitpid", pid, options))
        raise ChildProcessError
    monkeypatch.setattr(os, "waitpid", waitpid)
    return log


def end(p: subprocess.Popen):
    """Kill and reap a child of the test with the real calls: `calls` would only write them down."""
    if p.returncode is None:
        KILL(p.pid, signal.SIGKILL)
        p.returncode = -WAITPID(p.pid, 0)[1] or -signal.SIGKILL


@pytest.fixture
def no_proc(monkeypatch):
    """The test helpers behave as on macOS: there is no /proc to look at a process by."""
    monkeypatch.setattr(helpers, "_has_proc", lambda: False)


@pytest.mark.parametrize("pid", NOT_ONE_PROCESS)
def test_the_teardown_never_signals_a_pid_that_is_not_one_process_where_there_is_no_proc(calls, no_proc, pid):
    """What `conftest.reap` does with the pid in `hub.pid` on macOS."""
    helpers.stop_hub(pid)
    assert [c for c in calls if c[0] != "kill" or c[2] != 0] == []


@pytest.mark.parametrize("pid", NOT_ONE_PROCESS)
def test_the_teardown_never_signals_a_pid_that_is_not_one_process_where_there_is_a_proc(calls, pid):
    helpers.stop_hub(pid)
    assert [c for c in calls if c[0] != "kill" or c[2] != 0] == []


def test_the_teardown_never_signals_its_own_process(calls, no_proc):
    helpers.stop_hub(os.getpid())
    assert ("kill", os.getpid(), signal.SIGTERM) not in calls


# ── the guard itself ─────────────────────────────────────────────────────────

@pytest.fixture
def child():
    """A process of ours in a session of its own, so it leads its group. The signals of these tests never
    reach it (`calls` replaces them); `end` kills it."""
    p = subprocess.Popen(["sleep", "120"], start_new_session=True)
    yield p
    end(p)


@pytest.mark.parametrize("pid", NOT_ONE_PROCESS)
def test_a_pid_that_is_not_one_process_is_refused(calls, pid):
    with pytest.raises(signals.Refused, match="does not name one process"):
        signals.send(pid, signal.SIGTERM)
    assert calls == []


@pytest.mark.parametrize("pid", [-1, 0, 1])
def test_minus_one_zero_and_one_are_refused_where_there_is_no_proc(calls, monkeypatch, tmp_path, pid):
    """The refusal reads nothing: an empty /proc (macOS has none) changes nothing."""
    monkeypatch.setattr(signals, "PROC", tmp_path)
    with pytest.raises(signals.Refused):
        signals.send(pid, signal.SIGKILL)
    assert calls == []


def test_this_process_is_refused(calls):
    with pytest.raises(signals.Refused, match="is this process"):
        signals.send(os.getpid(), signal.SIGTERM)
    assert calls == []


def test_another_users_process_is_refused(calls, child, monkeypatch):
    monkeypatch.setattr(signals, "owner", lambda pid: os.getuid() + 1)
    with pytest.raises(signals.Refused, match="another user's process"):
        signals.send(child.pid, signal.SIGTERM)
    assert calls == []


def test_a_process_whose_user_cannot_be_read_is_refused(calls, child, monkeypatch):
    monkeypatch.setattr(signals, "owner", lambda pid: None)
    with pytest.raises(signals.Refused, match="cannot be read"):
        signals.send(child.pid, signal.SIGTERM)
    assert calls == [("kill", child.pid, 0)]                  # it is there: the probe sends nothing


def test_a_process_of_ours_is_signalled(calls, child):
    signals.send(child.pid, signal.SIGTERM)
    assert calls == [("kill", child.pid, signal.SIGTERM)]


def test_the_user_is_read_from_ps_where_there_is_no_proc(calls, child, monkeypatch, tmp_path):
    monkeypatch.setattr(signals, "PROC", tmp_path)
    assert signals.owner(child.pid) == os.getuid()
    signals.send(child.pid, signal.SIGTERM)
    assert calls == [("kill", child.pid, signal.SIGTERM)]


def test_a_group_is_signalled_through_the_child_that_leads_it(calls, child):
    signals.send_group(child, signal.SIGTERM)
    assert calls == [("killpg", child.pid, signal.SIGTERM)]


@pytest.mark.parametrize("pgid", [-1, 0, 1, 4242, None])
def test_a_group_is_never_a_number(calls, pgid):
    with pytest.raises(signals.Refused, match="not a child this process started"):
        signals.send_group(pgid, signal.SIGTERM)
    assert calls == []


def test_the_group_of_a_reaped_child_is_refused(calls):
    p = subprocess.Popen(["true"], start_new_session=True)
    p.communicate(timeout=30)
    with pytest.raises(signals.Refused, match="was reaped"):
        signals.send_group(p, signal.SIGTERM)
    assert calls == []


def test_a_child_in_the_callers_own_group_is_refused(calls):
    """Started without a session of its own, its group is this process's: killpg would reach the caller."""
    p = subprocess.Popen(["sleep", "120"])
    try:
        with pytest.raises(signals.Refused, match="does not lead a group of its own"):
            signals.send_group(p, signal.SIGTERM)
        assert calls == []
    finally:
        end(p)


@pytest.mark.parametrize("pid", [p for p in NOT_ONE_PROCESS if p != 1])
def test_a_probe_or_a_reap_of_a_pid_that_is_not_one_process_does_nothing(calls, pid):
    assert signals.exists(pid) is False
    signals.reap(pid)
    assert calls == []


def test_init_may_be_asked_about_and_is_never_reaped(calls):
    """Signal 0 sends nothing, so `exists(1)` asks; a session record that names init is then another account's."""
    signals.exists(1)
    signals.reap(1)
    assert calls == [("kill", 1, 0)]


def test_a_process_that_has_ended_is_said_as_os_kill_says_it(calls, monkeypatch):
    def kill(pid, sig):
        calls.append(("kill", pid, sig))
        raise ProcessLookupError
    monkeypatch.setattr(os, "kill", kill)
    monkeypatch.setattr(signals, "owner", lambda pid: None)
    with pytest.raises(ProcessLookupError):
        signals.send(4242, signal.SIGCONT)
    assert calls == [("kill", 4242, 0)]                       # the probe that found it gone, and nothing else


# ── every signal goes through the guard ──────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
RAW = {"kill", "killpg", "waitpid"}
GUARD = {ROOT / "src" / "sheafmd" / "signals.py", Path(__file__).resolve()}    # the guard, and this file's real ones


def raw_calls(path: Path):
    """Each `os.kill`, `os.killpg` or `os.waitpid` named in `path` (called or handed on, as to a Timer),
    except on a line that signals this very process (`os.getpid()`), which a test does on purpose."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for node in ast.walk(ast.parse(text)):
        if (isinstance(node, ast.Attribute) and node.attr in RAW and isinstance(node.value, ast.Name)
                and node.value.id == "os" and "os.getpid()" not in lines[node.lineno - 1]):
            yield f"{path.relative_to(ROOT)}:{node.lineno}: {lines[node.lineno - 1].strip()}"


def test_no_signal_is_sent_but_through_the_guard():
    found = [hit for folder in ("src", "tests", "tools") for path in sorted((ROOT / folder).rglob("*.py"))
             if path not in GUARD for hit in raw_calls(path)]
    assert found == []


def test_the_scan_sees_a_raw_kill(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    (tmp_path / "x.py").write_text("import os\nos.kill(pid, 9)\nos.kill(os.getpid(), 15)\nf(os.killpg)\n")
    assert list(raw_calls(tmp_path / "x.py")) == ["x.py:2: os.kill(pid, 9)", "x.py:4: f(os.killpg)"]
