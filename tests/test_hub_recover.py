"""`sheaf stop` and `sheaf restart` on a hub that holds its port and does not answer (SPEC 8.4, 9.4).

A hub under SIGSTOP (or hung) keeps its port and its connections and answers nothing, so the
challenge ends in `HubSilent` and nothing can ask it to stop. The two commands then stop the process
that the pid file names, and nothing else, when all of the rule holds (`recover.py`): the pid is the
pid file's and the file was written for this port, its command line is a sheaf hub's, it is this user's,
and it is the process that listens on the port. Every refusal below is one broken condition away from
a hub that is stopped: it leaves the process alone and says in the one line of its message which
condition broke (the message no longer sends the person to `sheaf restart`, which just refused).

The processes these tests signal are the ones the tests started themselves: a real hub, or a stand-in
whose command line is a hub's and that listens on a port of the test's own."""
import os
import signal
import subprocess
import sys
import time

import pytest

from helpers import (Silent, claim_port, gone, hub_rows, is_stopped, proc_state, silent_message, start_late_hub,
                     stranger, wait_until_refused)
from sheafmd.hub import client as hubclient
from sheafmd.hub import jobs, recover, server, state

HUB_TAIL = ("-m", "sheafmd", "hub", "--started-by", "cli")
WAIT = 0.5                    # what a command waits for an answer in these tests (hubclient.TIMEOUT)
USUAL = hubclient.TIMEOUT     # what it is outside them: a hub that is still starting listens before it answers

# A process that listens on a port, writes nothing back, and has a command line it is given: what a hub
# that does not run looks like from outside. `python -c CODE -m sheafmd hub ...` leaves `-m sheafmd hub
# ...` at the end of its command line, where a hub's is. It can ignore SIGTERM, as a hung hub does.
STAND_IN = r'''
import os, signal, socket, time
if os.environ.get("STAND_IN_IGNORES_TERM"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(os.environ["STAND_IN_PORT"])))
s.listen(5)
print("ready", flush=True)
while True:
    time.sleep(1)
'''


@pytest.fixture(autouse=True)
def short_wait(monkeypatch):
    monkeypatch.setattr(hubclient, "TIMEOUT", WAIT)


def nothing_stopped(port, command, why):
    """What `restart` or `stop` says when the rule names no process: the silence of 9.4 and why nothing was stopped."""
    return (f"the sheaf hub on 127.0.0.1:{port} did not answer within {WAIT:g} s, "
            f"and `sheaf {command}` stopped nothing: {why}")


def signals(log):
    return [s for _, _, s, _ in log]


@pytest.fixture
def stand_in():
    """A factory for a stand-in hub: `start(port, ignore_term=False, tail=HUB_TAIL)` is a Popen of our own."""
    made = []

    def start(listen, *, ignore_term=False, tail=HUB_TAIL):
        env = {**os.environ, "STAND_IN_PORT": str(listen), "STAND_IN_IGNORES_TERM": "1" if ignore_term else ""}
        p = subprocess.Popen([sys.executable, "-c", STAND_IN, *tail], env=env, stdout=subprocess.PIPE)
        made.append(p)
        assert p.stdout.readline().strip() == b"ready"
        return p
    yield start
    for p in made:
        p.kill()
        p.wait(timeout=30)


def write_pid_file(pid, port, **more):
    state.write_json(server.pid_file(), {"pid": pid, "boot": "b", "port": port, "service": False, **more})


@pytest.fixture
def stopped_hub(port, monkeypatch):
    """A real hub that holds the port and does not run (SIGSTOP). Yields its pid."""
    with monkeypatch.context() as usual:
        usual.setattr(hubclient, "TIMEOUT", USUAL)                      # a start waits as long as a person's does
        hubclient.ensure_hub("cli", lambda *a: None, lambda *a: None)
    pid = server.read_pid_file()["pid"]
    os.kill(pid, signal.SIGSTOP)
    for _ in range(200):
        if is_stopped(pid):
            break
        time.sleep(0.05)
    yield pid
    if proc_state(pid) == "alive":
        os.kill(pid, signal.SIGCONT)                                    # the reaper stops it from there


def answers():
    return hubclient.client().challenge()


# ── the command line of a hub ────────────────────────────────────────────────

@pytest.mark.parametrize("argv", [
    ["python", "-m", "sheafmd", "hub", "--started-by", "cli"],                       # a command's detached start
    ["/usr/bin/python3.12", "-m", "sheafmd", "hub", "--started-by", "upgrade"],
    ["/u/.local/share/uv/tools/sheafmd/bin/python", "/u/.local/bin/sheaf", "hub", "--started-by", "service"],
    ["python3", "/opt/sheaf/bin/sheaf", "hub", "--started-by", "service"],           # the script, run by its shebang
    ["python", "-m", "sheafmd", "hub"],                                              # run by hand in a terminal
    ["python", "/opt/sheaf/bin/sheaf", "hub"],
    ["pypy3", "-m", "sheafmd", "hub"],
    ["python", "-c", "import time", "-m", "sheafmd", "hub", "--started-by", "cli"]])  # the shape of the stand-in
def test_these_command_lines_are_a_hub(argv):
    assert recover.is_hub_command(b"\0".join(a.encode() for a in argv) + b"\0")


@pytest.mark.parametrize("argv", [
    ["python", "-m", "sheafmd", "mcp", "--agent", "claude-code"],                    # another sheaf process of ours
    ["python", "-m", "sheafmd", "status"],
    ["python", "-m", "sheafmd", "stop"],
    ["tail", "-f", "sheafmd.log"],                                                   # the name is in it
    ["vim", "sheafmd", "hub"],
    ["vim", "sheaf", "hub"],                                                         # `sheaf hub`, but not Python
    ["grep", "-m", "sheafmd", "hub"],                                                # `-m sheafmd hub`, not Python
    ["/opt/sheaf/bin/sheaf", "hub", "--started-by", "cli"],                          # no interpreter: not how it runs
    ["python", "-c", "import time", "sheafmd", "hub", "--started-by", "cli"],        # no -m
    ["python", "-m", "sheafmd", "hub", "--started-by"],                              # no value
    ["python", "-m", "sheafmd", "hub", "--started-by", "cli", "--more"],
    ["python", "/opt/mysheaf", "hub", "--started-by", "cli"],                        # a script that is not `sheaf`
    ["sh", "-c", "sheaf hub --started-by cli"],
    ["hub"], [], [""]])
def test_these_command_lines_are_not(argv):
    assert not recover.is_hub_command(b"\0".join(a.encode() for a in argv) + (b"\0" if argv else b""))


def test_an_unreadable_command_line_is_not_a_hub():
    assert not recover.is_hub_command(b"")


# ── restart and stop recover the hub; status does not touch it ───────────────

def test_restart_stops_a_hub_that_does_not_answer_and_starts_a_new_one(sheaf, port, stopped_hub):
    r = sheaf("restart")
    assert r.code == 0, r.err
    assert gone(stopped_hub)
    now = server.read_pid_file()
    assert now["pid"] != stopped_hub and answers()["app"] == "sheaf"
    assert f"stopped the sheaf hub (pid {stopped_hub}) that held 127.0.0.1:{port} and did not answer" in r.out
    assert f"hub restarted on 127.0.0.1:{port} (pid {now['pid']})" in r.out
    assert "killed" not in r.out and r.err == ""


def test_restart_waits_for_the_new_hub_while_it_listens_and_does_not_answer_yet(sheaf, port, stopped_hub, monkeypatch):
    """The new hub listens from its bind on and answers once it serves. The start waited for it with a bare
    challenge, which took that silence for a hub that does not answer: `sheaf restart` failed with "did not
    answer within 0.5 s" on a loaded CI runner."""
    monkeypatch.setattr(hubclient, "spawn_hub", lambda who: start_late_hub(who, late_by=4 * WAIT))
    r = sheaf("restart")
    assert r.code == 0, r.err
    now = server.read_pid_file()
    assert now["pid"] != stopped_hub and answers()["app"] == "sheaf"
    assert f"hub restarted on 127.0.0.1:{port} (pid {now['pid']})" in r.out and r.err == ""


def test_a_start_that_is_still_silent_when_its_wait_ends_fails_with_that_silence(port, stand_in, monkeypatch):
    """A start waits out the silence of a hub that is starting, for the start's own wait and no longer:
    a port that is held and silent at its end fails closed with the silence of 9.4, as it did at once."""
    monkeypatch.setattr(hubclient, "START_WAIT", 1.0)
    monkeypatch.setattr(hubclient, "spawn_hub", lambda who: stand_in(port))
    with pytest.raises(hubclient.HubSilent) as e:
        hubclient.ensure_hub("cli", lambda *a: None, lambda *a: None)
    assert str(e.value) == (f"the sheaf hub on 127.0.0.1:{port} did not answer within {WAIT:g} s; "
                            "try again, or run `sheaf restart`")


def test_stop_stops_a_hub_that_does_not_answer_and_nothing_listens_after(sheaf, port, stopped_hub):
    r = sheaf("stop")
    assert r.code == 0, r.err
    assert gone(stopped_hub) and wait_until_refused(port, 5)
    assert answers() is None
    assert f"stopped the sheaf hub (pid {stopped_hub}) that held 127.0.0.1:{port} and did not answer" in r.out
    assert r.out.rstrip().endswith("hub stopped") and r.err == ""


def test_status_stays_read_only_on_a_hub_that_does_not_answer(sheaf, port, stopped_hub, sent):
    before = server.pid_file().read_bytes()
    r = sheaf("status")
    assert r.code == 1 and f"! {silent_message(port, WAIT)}" in r.err
    assert sent == [] and proc_state(stopped_hub) == "alive"
    assert is_stopped(stopped_hub)                                                           # still stopped
    assert server.pid_file().read_bytes() == before


def test_the_hub_that_goes_on_sigterm_writes_its_exit_and_the_grace_period_is_not_spent(
        sheaf, port, stopped_hub, sent, monkeypatch):
    """A stopped process runs no handler until it is continued: SIGTERM alone would wait out the whole
    grace and end in SIGKILL, with no exit row and the jobs' process groups left running. The grace is
    set far above what the test can take, and `stop` is timed, so a hub that waited for it fails on
    the clock and on `killed`."""
    monkeypatch.setattr(recover, "GRACE", 60.0)
    took, real = [], recover.HubProcess.stop

    def timed(self):
        t = time.monotonic()
        out = real(self)
        took.append((time.monotonic() - t, out))
        return out
    monkeypatch.setattr(recover.HubProcess, "stop", timed)
    boot = server.read_pid_file()["boot"]
    r = sheaf("stop")
    assert r.code == 0, r.err
    (seconds, outcome), = took
    assert outcome.ended and not outcome.killed and seconds < 30          # on a free box a second or two
    assert signals(sent) == [signal.SIGTERM, signal.SIGCONT]              # no SIGKILL, whatever the grace
    assert [(x["boot"], x["reason"]) for x in hub_rows("hub-exit")] == [(boot, "signal")]


# ── the order: SIGTERM, the grace period, then SIGKILL ───────────────────────

def test_the_grace_period_is_as_long_as_a_stop_waits_for_the_hub():
    """A hub that obeys SIGTERM kills its jobs first: up to `jobs.TERM_GRACE` for a child that ignores
    it, a second more after SIGKILL, then the exit row, and `hubclient.STOP_WAIT` is what a stop that
    the hub answers waits for all of it. A shorter grace would SIGKILL a hub that is doing as it was
    told, and the message would say it ignored SIGTERM."""
    assert recover.GRACE == hubclient.STOP_WAIT == 8.0
    assert recover.GRACE > jobs.TERM_GRACE + 1


def test_a_hub_that_ignores_sigterm_gets_sigkill_after_the_grace_period_and_not_before(
        sheaf, port, stand_in, sent, monkeypatch):
    monkeypatch.setattr(recover, "GRACE", 1.0)
    p = stand_in(port, ignore_term=True)
    write_pid_file(p.pid, port)
    r = sheaf("stop")
    assert r.code == 0, r.err
    assert signals(sent) == [signal.SIGTERM, signal.SIGCONT, signal.SIGKILL]
    term, kill = sent[0], sent[2]
    assert kill[0] - term[0] >= 1.0                                     # not before the grace period is over
    assert kill[3]                                                      # it still ran when SIGKILL came
    assert p.wait(timeout=30) == -signal.SIGKILL
    assert "ignored SIGTERM for 1 s and was killed" in r.out


def test_a_hub_that_ends_on_sigterm_is_never_sent_sigkill(sheaf, port, stand_in, sent):
    p = stand_in(port)
    write_pid_file(p.pid, port)
    r = sheaf("restart")
    assert r.code == 0, r.err
    assert signals(sent) == [signal.SIGTERM, signal.SIGCONT]
    assert p.wait(timeout=30) == -signal.SIGTERM
    assert "killed" not in r.out and answers()["app"] == "sheaf"   # and the usual start came after


def test_a_process_that_outlives_sigkill_is_said_and_the_command_fails(
        sheaf, port, stand_in, monkeypatch):
    """A process in the kernel's hands may not end even on SIGKILL: the command says which one."""
    monkeypatch.setattr(recover, "GRACE", 0.2)
    monkeypatch.setattr(recover, "KILL_WAIT", 0.2)
    monkeypatch.setattr(recover.HubProcess, "send", lambda self, sig: None)       # nothing reaches it
    p = stand_in(port)
    write_pid_file(p.pid, port)
    r = sheaf("stop")
    assert r.code == 1 and f"pid {p.pid}" in r.err and "did not end" in r.err and "SIGKILL" in r.err
    assert p.poll() is None


# ── each refusal of the rule leaves the process alone and keeps the message ──

def refused(sheaf, command, port, sent, *processes, why):
    """`why`: the one line that says what the rule did not find, in the message and nowhere else."""
    before = server.pid_file().read_bytes() if server.pid_file().exists() else None
    r = sheaf(command)
    assert r.code == 1 and r.err.strip() == f"! {nothing_stopped(port, command, why)}", (r.out, r.err)
    assert "stopped the sheaf hub" not in r.out
    assert sent == []
    for p in processes:
        assert p.poll() is None
    after = server.pid_file().read_bytes() if server.pid_file().exists() else None
    assert after == before


@pytest.fixture
def stranger_that_says_nothing(port):
    fake = Silent(port, "hold")
    yield fake
    fake.close()


@pytest.fixture
def harmless():
    """A process of ours that is no hub, for a pid file to name."""
    p = subprocess.Popen(["sleep", "120"])
    yield p
    p.kill()
    p.wait(timeout=30)


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_pid_that_is_not_a_sheaf_hub_is_left_alone(sheaf, port, harmless, stranger_that_says_nothing, sent, command):
    """The pid was reused by something else, or the file is old."""
    write_pid_file(harmless.pid, port)
    refused(sheaf, command, port, sent, harmless, why=f"pid {harmless.pid} is not a sheaf hub")


@pytest.mark.parametrize("command", ["restart", "stop"])
@pytest.mark.parametrize("tail", [
    ("-m", "sheafmd", "mcp", "--agent", "claude-code"),          # another sheaf process of this user
    ("sheafmd", "hub", "--started-by", "cli"),                   # the name and the words, no -m
    ("-m", "sheafmd", "status")])
def test_another_process_with_sheafmd_in_its_command_line_is_left_alone(
        sheaf, port, stand_in, stranger_that_says_nothing, sent, command, tail):
    """The check that `tests/helpers.py::stop_hub` makes (the name anywhere in the command line) would
    pass these; the product's does not."""
    p = stand_in(claim_port()[0], tail=tail)
    write_pid_file(p.pid, port)
    refused(sheaf, command, port, sent, p, why=f"pid {p.pid} is not a sheaf hub")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_pid_file_whose_process_has_ended_names_nothing(sheaf, port, stranger_that_says_nothing, sent, command):
    p = subprocess.Popen(["true"])
    p.wait(timeout=30)
    write_pid_file(p.pid, port)
    refused(sheaf, command, port, sent, why=f"pid {p.pid} is not running")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_no_pid_file_names_nothing(sheaf, port, stranger_that_says_nothing, sent, command):
    assert not server.pid_file().exists()
    refused(sheaf, command, port, sent, why="there is no pid file that names a process")


@pytest.mark.parametrize("command", ["restart", "stop"])
@pytest.mark.parametrize("pid", [-1, 0, 1, 2 ** 40, 1.0, "1", True, None, [1]])
def test_a_pid_that_is_not_one_process_is_never_signalled(sheaf, port, stranger_that_says_nothing, sent, command, pid):
    """-1 is every process this user may signal, 0 the caller's own group, and `True` is 1 in JSON."""
    write_pid_file(pid, port)
    refused(sheaf, command, port, sent, why="the pid file names no process" if pid else
            "there is no pid file that names a process")             # a 0 or a null is a pid file with no pid


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_the_process_of_the_command_itself_is_never_signalled(sheaf, port, stranger_that_says_nothing, sent, command):
    write_pid_file(os.getpid(), port)
    refused(sheaf, command, port, sent, why="the pid file names the command's own process")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_process_of_another_user_is_left_alone(sheaf, port, stand_in, sent, monkeypatch, command):
    """Everything else holds (a hub's command line, the pid file's pid and port, the listener): only the
    uid is another. No second user is needed: the reading of /proc/<pid>/status is the one thing replaced."""
    p = stand_in(port)
    write_pid_file(p.pid, port)
    monkeypatch.setattr(recover, "read_uids", lambda pid: (os.getuid() + 1,) * 4)
    refused(sheaf, command, port, sent, p, why=f"pid {p.pid} is another user's process")


MINE, OTHER = "mine", "other"     # the runner's uid, and one that is not: never a literal, since root's is 0


@pytest.mark.parametrize("command", ["restart", "stop"])
@pytest.mark.parametrize("uids", [(OTHER,) * 4, (MINE, MINE, MINE, OTHER), (OTHER, MINE, MINE, MINE), None])
def test_a_process_whose_real_effective_saved_or_filesystem_uid_is_not_ours_is_left_alone(
        sheaf, port, stand_in, sent, monkeypatch, command, uids):
    """Another user's uid is the runner's plus one, so each case means the same for every runner, root
    among them."""
    p = stand_in(port)
    write_pid_file(p.pid, port)
    mine = os.getuid()
    as_read = {MINE: mine, OTHER: mine + 1}
    monkeypatch.setattr(recover, "read_uids", lambda pid: None if uids is None else
                        tuple(as_read[u] for u in uids))
    refused(sheaf, command, port, sent, p, why=f"the user of pid {p.pid} cannot be read" if uids is None
            else f"pid {p.pid} is another user's process")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_hub_whose_pid_file_was_written_for_another_port_is_left_alone(
        sheaf, port, stand_in, stranger_that_says_nothing, sent, command):
    p = stand_in(claim_port()[0])
    write_pid_file(p.pid, port + 1)
    refused(sheaf, command, port, sent, p, why=f"the pid file was written for port {port + 1}, not {port}")


@pytest.mark.parametrize("command", ["restart", "stop"])
@pytest.mark.parametrize("written", [None, "27419", 27419.0, True])
def test_a_pid_file_that_does_not_say_a_port_leaves_the_hub_alone(
        sheaf, port, stand_in, stranger_that_says_nothing, sent, command, written):
    p = stand_in(claim_port()[0])
    write_pid_file(p.pid, written)
    refused(sheaf, command, port, sent, p, why="the pid file does not say which port it was written for")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_hub_that_does_not_hold_the_port_is_left_alone_though_the_pid_file_names_it(
        sheaf, port, stand_in, stranger_that_says_nothing, sent, command):
    """The pid file says this port and the process is a sheaf hub of ours, but what holds the port is
    the stranger: the process is a hub of another port (or the pid was handed to one)."""
    other = stand_in(claim_port()[0])
    write_pid_file(other.pid, port)
    refused(sheaf, command, port, sent, other, why=f"pid {other.pid} does not hold 127.0.0.1:{port}")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_stranger_that_answers_is_not_a_silent_hub_and_nothing_is_signalled(
        sheaf, port, harmless, sent, command):
    s = stranger(port)
    try:
        write_pid_file(harmless.pid, port)
        r = sheaf(command)
    finally:
        s.close()
    assert r.code == 1 and f"! something else holds 127.0.0.1:{port}, not your sheaf hub" in r.err
    assert sent == [] and harmless.poll() is None


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_without_a_proc_nothing_is_stopped_and_the_message_is_the_one_it_was(
        sheaf, port, stand_in, sent, monkeypatch, command):
    """macOS has no /proc: v1 is Linux, and there a silent hub keeps the message."""
    p = stand_in(port)
    write_pid_file(p.pid, port)
    monkeypatch.setattr(recover, "PLATFORM", "darwin")
    refused(sheaf, command, port, sent, p, why="this system has no /proc to check a process by")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_proc_that_cannot_be_read_stops_nothing(sheaf, port, stand_in, sent, monkeypatch, tmp_path, command):
    p = stand_in(port)
    write_pid_file(p.pid, port)
    monkeypatch.setattr(recover, "PROC", tmp_path / "no-proc-here")
    refused(sheaf, command, port, sent, p, why="this system has no /proc to check a process by")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_process_whose_command_line_cannot_be_read_is_left_alone(
        sheaf, port, stand_in, sent, monkeypatch, tmp_path, command):
    """The process is there and holds the port, but /proc/<pid>/cmdline is not: the rule cannot say it is
    a hub. A /proc of the test's own, with every file of it but that one."""
    p = stand_in(port)
    write_pid_file(p.pid, port)
    fake = tmp_path / "proc"
    (fake / "self").mkdir(parents=True)
    (fake / "self" / "stat").write_text((recover.PROC / "self" / "stat").read_text())
    (fake / str(p.pid)).mkdir()
    (fake / str(p.pid) / "stat").write_text((recover.PROC / str(p.pid) / "stat").read_text())
    monkeypatch.setattr(recover, "PROC", fake)
    refused(sheaf, command, port, sent, p, why=f"the command line of pid {p.pid} cannot be read")


@pytest.mark.parametrize("command", ["restart", "stop"])
def test_a_process_that_changes_while_the_rule_is_read_is_left_alone(sheaf, port, stand_in, sent, monkeypatch, command):
    """Every condition holds, and the start time read after them is another: the pid was handed on."""
    p = stand_in(port)
    write_pid_file(p.pid, port)
    real, calls = recover.read_stat, []

    def other_the_second_time(pid):
        calls.append(pid)
        got = real(pid)
        return got if len(calls) == 1 else (got[0], got[1] + 1)
    monkeypatch.setattr(recover, "read_stat", other_the_second_time)
    refused(sheaf, command, port, sent, p, why=f"pid {p.pid} changed while it was checked")


def test_a_port_that_is_not_a_number_names_no_process(port):
    with pytest.raises(recover.Refusal, match="the port is not a number"):
        recover.find(str(port))


def test_a_process_that_started_after_the_rule_was_read_is_not_signalled(sheaf, port, stand_in, monkeypatch):
    """The pid was handed on between the reading and the signal: the start time is another."""
    p = stand_in(port)
    write_pid_file(p.pid, port)
    hub = recover.find(port)
    assert hub is not None and hub.pid == p.pid
    real = recover.read_stat
    monkeypatch.setattr(recover, "read_stat", lambda pid: (lambda got: (got[0], got[1] + 1))(real(pid)))
    done = hub.stop()
    assert done.ended and not done.killed                    # nothing there it knows, so nothing was sent
    assert p.poll() is None


def test_a_process_that_changes_while_the_rule_is_read_is_not_named(port, stand_in, monkeypatch):
    p = stand_in(port)
    write_pid_file(p.pid, port)
    real, calls = recover.read_stat, []

    def other_the_second_time(pid):
        calls.append(pid)
        got = real(pid)
        return got if len(calls) == 1 else (got[0], got[1] + 1)
    monkeypatch.setattr(recover, "read_stat", other_the_second_time)
    with pytest.raises(recover.Refusal, match=f"pid {p.pid} changed while it was checked"):
        recover.find(port)
    assert len(calls) == 2 and p.poll() is None


def test_a_hub_whose_state_changes_while_the_rule_is_read_is_still_named(port, stand_in, monkeypatch):
    """A hung hub flips between running, sleeping and waiting; only its start time says which process it is."""
    p = stand_in(port)
    write_pid_file(p.pid, port)
    real, calls = recover.read_stat, []

    def flips(pid):
        calls.append(pid)
        got = real(pid)
        return got if len(calls) == 1 else ("D", got[1])
    monkeypatch.setattr(recover, "read_stat", flips)
    hub = recover.find(port)
    assert hub is not None and hub.pid == p.pid and len(calls) == 2


# ── the control: the same stand-in, with every condition true, is stopped ────

@pytest.mark.parametrize("command", ["restart", "stop"])
def test_the_stand_in_with_every_condition_true_is_stopped(sheaf, port, stand_in, sent, command):
    p = stand_in(port)
    write_pid_file(p.pid, port)
    r = sheaf(command)
    assert r.code == 0, r.err
    assert p.wait(timeout=30) == -signal.SIGTERM
    assert f"(pid {p.pid})" in r.out
    assert signals(sent) == [signal.SIGTERM, signal.SIGCONT]


def test_the_pid_file_of_the_command_is_the_one_in_the_state_folder_of_this_user(sheaf, port, stand_in, sent):
    """The rule reads the pid file of `server.pid_file()` and no other: a stand-in named by a pid file
    elsewhere is not found."""
    p = stand_in(port)
    elsewhere = server.pid_file().with_name("hub.pid.old")
    state.write_json(elsewhere, {"pid": p.pid, "boot": "b", "port": port, "service": False})
    refused(sheaf, "stop", port, sent, p, why="there is no pid file that names a process")


def test_a_hub_that_runs_is_stopped_the_way_it_always_was(sheaf, port):
    """No silence, no recovery: the ordinary stop does not touch the new code."""
    assert sheaf("start").code == 0
    pid = server.read_pid_file()["pid"]
    r = sheaf("stop")
    assert r.code == 0 and "hub stopped" in r.out and "stopped the sheaf hub" not in r.out
    assert gone(pid)
