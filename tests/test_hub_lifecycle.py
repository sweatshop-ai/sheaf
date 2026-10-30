"""The hub as a process, from its start to its exit (SPEC 8.4): what the diagnostics log holds
after a clean stop, a lost start race and a kill -9. Every hub here is a real `python -m sheafmd
hub` under this test's own SHEAF_HOME and port, and every one is reaped."""
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from helpers import gone, hub_rows, key, stranger
from sheafmd import diagnostics, signals
from sheafmd.hub import sender, server
from sheafmd.hub.jobs import Job, Jobs


def run_hub(*extra):
    return subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", *extra],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def alive(port) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        return True
    except OSError:
        return False


def wait_alive(port):
    """The hub is up: it has bound the port, written its pid file and then its hub-start row (the
    row comes last, so a test that reads the log must wait for it too)."""
    for _ in range(200):
        info = server.read_pid_file()
        if alive(port) and info and hub_rows("hub-start") and info["boot"] in {r["boot"] for r in hub_rows("hub-start")}:
            return
        time.sleep(0.05)
    pytest.fail("the hub did not start")


def kill_hard(p):
    """kill -9: the hub leaves no hub-exit row and no cleanup; its pid file stays behind, as
    after a power cut, and a person (or the next start) finds it stale."""
    p.kill()
    p.wait(timeout=30)
    for _ in range(100):
        if gone(p.pid):
            break
        time.sleep(0.05)
    server.pid_file().unlink(missing_ok=True)


def test_a_kill_9_leaves_an_unclean_exit_row_at_the_next_start_naming_the_dead_boot(port):
    first = run_hub("--started-by", "cli")
    wait_alive(port)
    dead_boot = server.read_pid_file()["boot"]
    kill_hard(first)
    second = run_hub("--started-by", "cli")
    try:
        wait_alive(port)
        starts, unclean = hub_rows("hub-start"), hub_rows("unclean-exit")
        assert len(starts) == 2 and len(unclean) == 1
        assert unclean[0]["boot"] == dead_boot == starts[0]["boot"] != starts[1]["boot"]
        assert unclean[0]["port"] == port and unclean[0]["started"] == starts[0]["at"]
        # the row comes before this boot's hub-start, so the log reads in the order it happened
        order = [r["kind"] for r in hub_rows("hub-start", "unclean-exit")]
        assert order == ["hub-start", "unclean-exit", "hub-start"]
    finally:
        second.terminate()
        second.wait(timeout=30)


def test_a_clean_stop_leaves_no_unclean_exit_row_at_the_next_start(port):
    first = run_hub("--started-by", "cli")
    wait_alive(port)
    first.send_signal(signal.SIGTERM)
    assert first.wait(timeout=30) == 0
    second = run_hub("--started-by", "cli")
    try:
        wait_alive(port)
        assert [r["kind"] for r in hub_rows("hub-start", "hub-exit", "unclean-exit")] == \
            ["hub-start", "hub-exit", "hub-start"]
    finally:
        second.terminate()
        second.wait(timeout=30)


def test_a_crash_that_wrote_its_own_exit_row_is_not_an_unclean_exit(port):
    # a hub that died by its own hand (reason crash) said so; only silence is unclean
    diagnostics.record("hub", "hub-start", None, boot="b-old", port=port, started_by="cli")
    diagnostics.record("hub", "hub-exit", None, boot="b-old", reason="crash")
    p = run_hub("--started-by", "cli")
    try:
        wait_alive(port)
        assert hub_rows("unclean-exit") == []
    finally:
        p.terminate()
        p.wait(timeout=30)


def test_the_loser_of_a_start_race_writes_neither_hub_start_nor_unclean_exit_nor_hub_exit(port):
    # The winner's hub-start has no hub-exit yet because it is running. A loser that looked at
    # the log before it tried the port would call that an unclean exit.
    first = run_hub("--started-by", "cli")
    try:
        wait_alive(port)
        second = run_hub("--started-by", "cli")
        _, err = second.communicate(timeout=30)
        assert second.returncode == 1 and "already in use" in err
        assert [r["kind"] for r in hub_rows()] == ["hub-start", "port-taken"]
        assert hub_rows("port-taken")[0]["pid"] == second.pid
        assert server.read_pid_file()["pid"] == first.pid       # the winner's pid file is untouched
    finally:
        first.terminate()
        first.wait(timeout=30)


def test_a_kill_9_of_the_winner_is_not_hidden_by_a_loser(port):
    first = run_hub("--started-by", "cli")
    wait_alive(port)
    dead_boot = server.read_pid_file()["boot"]
    second = run_hub("--started-by", "cli")
    second.communicate(timeout=30)
    assert second.returncode == 1
    kill_hard(first)
    third = run_hub("--started-by", "cli")
    try:
        wait_alive(port)
        assert [r["boot"] for r in hub_rows("unclean-exit")] == [dead_boot]
    finally:
        third.terminate()
        third.wait(timeout=30)


def test_a_hub_that_has_written_hub_start_already_stops_cleanly_on_sigterm(port, monkeypatch):
    # A SIGTERM between the bind and the handler would end the hub with no exit row, and the next
    # start would call that an unclean exit. In-process, on the main thread, where signals work.
    seen = {}
    real = diagnostics.record

    def record(source, kind, doc=None, **detail):
        if kind == "hub-start":
            seen["handler"] = signal.getsignal(signal.SIGTERM)
            threading.Timer(0.3, os.kill, (os.getpid(), signal.SIGTERM)).start()
        return real(source, kind, doc, **detail)
    monkeypatch.setattr(diagnostics, "record", record)
    old_term, old_int = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    try:
        assert server.run("cli") == 0
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
    assert seen["handler"] not in (signal.SIG_DFL, signal.SIG_IGN, None)
    assert [r["reason"] for r in hub_rows("hub-exit")] == ["signal"]


# ── sheaf restart ────────────────────────────────────────────────────────────

def test_restart_with_no_hub_starts_one(sheaf, port):
    r = sheaf("restart")
    assert r.code == 0 and f"hub started on 127.0.0.1:{port}" in r.out
    assert server.read_pid_file()["port"] == port


def test_restart_replaces_the_hub_and_open_tabs_ride_through_without_a_stop_banner(sheaf, port):
    sheaf("start")
    before = server.read_pid_file()
    r = sheaf("restart")
    after = server.read_pid_file()
    assert r.code == 0 and f"hub restarted on 127.0.0.1:{port} (pid {after['pid']})" in r.out
    assert after["pid"] != before["pid"] and after["boot"] != before["boot"]
    assert after["version"] == before["version"]
    exits = hub_rows("hub-exit")
    assert [(x["boot"], x["reason"]) for x in exits] == [(before["boot"], "upgrade")]
    assert hub_rows("unclean-exit") == []
    assert [x["kind"] for x in hub_rows("hub-start", "hub-exit")] == ["hub-start", "hub-exit", "hub-start"]


def test_restart_forces_the_upgrade_stop_because_the_person_asked_for_it(sheaf, port, monkeypatch):
    """A hub refuses an upgrade stop while an Ask or Tell runs (8.4); `sheaf restart` is the person's
    own decision, so what it posts says `force`."""
    from sheafmd.hub import client as hubclient
    sheaf("start")
    real, sent = hubclient.HubClient.call, []

    def call(self, method, path, body=None):
        if path == "/_/stop":
            sent.append(body)
        return real(self, method, path, body)
    monkeypatch.setattr(hubclient.HubClient, "call", call)
    assert sheaf("restart").code == 0
    assert sent == [{"reason": "upgrade", "force": True}]


def test_restart_names_a_port_that_something_else_holds(sheaf, port):
    s = stranger(port)
    try:
        r = sheaf("restart")
        assert r.code == 1 and "something else holds" in r.err and hub_rows("hub-start") == []
    finally:
        s.close()


def test_a_sigterm_that_arrives_while_the_port_is_being_bound_is_still_a_clean_stop(port, monkeypatch):
    # The port is listening from the bind on, so a command may stop the hub from that instant.
    real = server.bind

    def bind(p):
        sock = real(p)
        os.kill(os.getpid(), signal.SIGTERM)
        return sock
    monkeypatch.setattr(server, "bind", bind)
    old_term, old_int = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    try:
        assert server.run("cli") == 0
    finally:
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
    assert [(r["kind"], r.get("reason")) for r in hub_rows("hub-start", "hub-exit", "unclean-exit")] == \
        [("hub-start", None), ("hub-exit", "signal")]
    assert server.read_pid_file() is None


# ── who sent the signal ─────────────────────────────────

LINUX_SIGINFO = hasattr(signal, "sigtimedwait")
SENDER = ("import os, signal, sys, time\n"
          "from sheafmd import signals\n"
          "signals.send(int(sys.argv[1]), getattr(signal, sys.argv[2]))\n"
          "time.sleep(60)\n")


def signalled_by_a_known_process(port, name):
    """A real hub, a signal from a process the test started (it stays alive, so the test knows its
    pid and its command line), and the hub-exit row the hub left."""
    hub = run_hub("--started-by", "cli")
    wait_alive(port)
    killer = subprocess.Popen([sys.executable, "-c", SENDER, str(hub.pid), name])
    try:
        assert hub.wait(timeout=30) == 0
        rows = hub_rows("hub-exit")
    finally:
        killer.kill()
        killer.wait(timeout=30)
    assert [r["reason"] for r in rows] == ["signal"]
    return rows[0], killer


@pytest.mark.skipif(not LINUX_SIGINFO, reason="the sender of a signal is read where the OS gives siginfo")
@pytest.mark.parametrize("name", ["SIGTERM", "SIGINT"])
def test_the_exit_row_of_a_signal_names_the_signal_and_who_sent_it(port, name):
    row, killer = signalled_by_a_known_process(port, name)
    assert row["signal"] == name
    assert row["sender_pid"] == killer.pid and row["sender_uid"] == os.getuid()
    # /proc/<pid>/cmdline is NUL-separated; the row holds it with spaces, whole
    assert row["sender_cmdline"] == " ".join([sys.executable, "-c", SENDER, str(row["pid"]), name])
    assert row["sender_cmdline"].startswith(f"{sys.executable} -c import os, signal")


def siginfo(signo, code=0, pid=0, uid=0):
    return signal.struct_siginfo((signo, code, 0, pid, uid, 0, 0))


def test_a_siginfo_that_names_no_stopping_signal_is_written_as_its_raw_numbers():
    """The row of sheaf#78 said `"signal": "-1532110032", "sender_pid": 443239200`: no signal, and
    a pid above pid_max. A siginfo that names neither SIGTERM nor SIGINT is no sender to name."""
    row = sender.who(siginfo(-1532110032, code=-1532110000, pid=443239200, uid=7))
    assert row == {"signal": "unknown",
                   "raw": {"si_signo": -1532110032, "si_code": -1532110000, "si_pid": 443239200, "si_uid": 7}}


def test_the_watcher_takes_only_a_stopping_signal_and_logs_the_rest(monkeypatch):
    """CPython's sigtimedwait, interrupted (EINTR) once its deadline has passed, returns the
    siginfo it never filled in instead of None (sheaf#78). The hub stopped on it."""
    waits = iter([siginfo(-1532110032, pid=443239200), None, siginfo(signal.SIGTERM, pid=4242, uid=995)])
    held = sender.Signals.__new__(sender.Signals)
    held._done = threading.Event()
    delivered = []

    def fake_wait(sigset, timeout):
        info = next(waits)
        if info is not None and info.si_signo == signal.SIGTERM:
            held._done.set()
        return info
    monkeypatch.setattr(sender.signal, "sigtimedwait", fake_wait)
    held._wait(lambda signum, fields: delivered.append((signum, fields)))
    assert delivered == [(signal.SIGTERM, {"signal": "SIGTERM", "sender_pid": 4242, "sender_uid": 995})]
    row, = hub_rows("signal-unread")
    assert row["raw"] == {"si_signo": -1532110032, "si_code": 0, "si_pid": 443239200, "si_uid": 0}


@pytest.mark.skipif(not LINUX_SIGINFO, reason="the signals are taken with sigtimedwait where the OS gives siginfo")
def test_a_hub_that_is_stopped_and_continued_keeps_running(port):
    """A stop and SIGCONT (a debugger, a freezer, kill -STOP) interrupt sigtimedwait; past its
    deadline that gave the siginfo nobody filled in, and the hub exited as if signalled (sheaf#78)."""
    hub = run_hub("--started-by", "cli")
    try:
        wait_alive(port)
        for _ in range(3):
            signals.send(hub.pid, signal.SIGSTOP)
            time.sleep(4 * sender.POLL)
            signals.send(hub.pid, signal.SIGCONT)
            time.sleep(2 * sender.POLL)
        assert hub.poll() is None and alive(port)
        assert not hub_rows("hub-exit")
        assert hub_rows("signal-unread")
    finally:
        hub.terminate()
        hub.wait(timeout=30)
    row, = hub_rows("hub-exit")
    assert row["signal"] == "SIGTERM"


@pytest.mark.skipif(LINUX_SIGINFO, reason="this platform gives the sender")
def test_where_the_os_gives_no_sender_the_row_names_the_signal_only(port):
    hub = run_hub("--started-by", "cli")
    wait_alive(port)
    hub.send_signal(signal.SIGTERM)
    assert hub.wait(timeout=30) == 0
    row, = hub_rows("hub-exit")
    assert row["signal"] == "SIGTERM" and "sender_pid" not in row and "sender_cmdline" not in row


def test_a_stop_by_the_door_is_not_a_signal_and_names_no_sender(port):
    hub = run_hub("--started-by", "cli")
    wait_alive(port)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/_/stop", data=b'{"reason": "stop"}', method="POST",
                                 headers={"X-Sheaf-Key": key(), "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).close()
    assert hub.wait(timeout=30) == 0
    row, = hub_rows("hub-exit")
    assert row["reason"] == "stop" and not {"signal", "sender_pid", "sender_cmdline"} & row.keys()


@pytest.mark.skipif(not LINUX_SIGINFO, reason="the mask is only set where the OS gives siginfo")
def test_no_child_the_hub_starts_inherits_the_blocked_signals():
    """The hub blocks SIGTERM and SIGINT in every thread so that one thread can take the siginfo;
    a child it starts (a job, a PDF render, git) is sent SIGTERM and must not have it blocked."""
    mask = ["grep", "SigBlk", "/proc/self/status"]          # not via sh: dash clears its mask
    both = (1 << (signal.SIGTERM - 1)) | (1 << (signal.SIGINT - 1))
    seen = {}

    def in_the_hub():
        held = sender.Signals()
        try:
            assert {signal.SIGTERM, signal.SIGINT} <= signal.pthread_sigmask(signal.SIG_BLOCK, set())
            seen["run"] = int(subprocess.run(mask, capture_output=True, text=True).stdout.split()[1], 16)
            seen["job"] = int(Job(Jobs(), "ask", "a", "c1").run(mask, timeout=20).stdout.split()[1], 16)
            seen["after"] = signal.pthread_sigmask(signal.SIG_BLOCK, set())     # the thread is blocked again
        finally:
            held.close()

    def a_worker_that_outlives_the_hub():
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM, signal.SIGINT})     # made while it was blocked
        seen["late"] = int(subprocess.run(mask, capture_output=True, text=True).stdout.split()[1], 16)
    t = threading.Thread(target=in_the_hub)
    t.start()
    t.join(30)
    w = threading.Thread(target=a_worker_that_outlives_the_hub)
    w.start()
    w.join(30)
    assert seen["run"] & both == 0 and seen["job"] & both == 0 and seen["late"] & both == 0
    assert {signal.SIGTERM, signal.SIGINT} <= seen["after"]


@pytest.mark.skipif(not LINUX_SIGINFO, reason="the command line is read from /proc")
def test_a_sender_command_line_keeps_a_byte_that_is_not_utf8_as_the_log_escapes_it(port):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", b"\xff", b" a "])
    try:
        # Popen returns when the exec has begun, a moment before the kernel has set the arguments
        # that /proc/<pid>/cmdline shows: until then it is empty and cmdline() is None.
        deadline = time.monotonic() + 30
        while (line := sender.cmdline(p.pid)) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert line is not None
        assert line.endswith("\udcff  a ")            # the whitespace of an argument stays
        assert "\udcff" in line                       # not U+FFFD: two different bytes stay two different rows
        assert diagnostics.record("hub", "hub-exit", None, reason="signal", sender_cmdline=line)
        assert "\\udcff" in hub_rows("hub-exit")[0]["sender_cmdline"]          # written as its escape (SPEC 15)
    finally:
        p.kill()
        p.wait(timeout=30)
