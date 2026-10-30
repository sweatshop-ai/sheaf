"""A newer `sheaf` meets a hub of another version (SPEC 8.4, 14.4, D14): an idle hub restarts, a
busy one is left alone, an older command only says so. Under the service the hub exits 75 and the
supervisor starts the new code; without it the hub exits 0 and the command starts the new one.

The hubs are real `python -m sheafmd hub` processes whose version is patched before the package
is used, so "the hub is older" needs no second install. systemd is not here: `Supervisor` does
what `Restart=always` with `RestartPreventExitStatus` does, so the exit code is what is under test."""
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

from helpers import gone, hub_rows, start_late_hub
from sheafmd import __version__, cli, paths
from sheafmd.hub import client as hubclient
from sheafmd.hub import jobs, server, service, state
from sheafmd.hub.core import Hub

OLD = "0.0.1"


def start_old_hub(started_by, version=OLD):
    code = (f"import sheafmd; sheafmd.__version__ = {version!r}\n"
            "from sheafmd.cli import main\n"
            f"raise SystemExit(main(['hub', '--started-by', {started_by!r}]))")
    # Under `sh`, as a hub under a service manager is not the child of the command that meets it:
    # the command reaps only its own children, and would take this exit code with it.
    return subprocess.Popen(["sh", "-c", '"$0" -c "$1"; exit $?', sys.executable, code],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def start_hub(started_by, env=None):
    return subprocess.Popen([sys.executable, "-m", "sheafmd", "hub", "--started-by", started_by],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)


def unit_env():
    """The environment the unit of 14.3 gives the hub: it names the exit it leaves down."""
    return {**os.environ, service.STOP_EXIT_ENV: str(server.EXIT_STOPPED)}


class Supervisor:
    """`Restart=always` and `RestartPreventExitStatus=<EXIT_STOPPED>`: when the hub it runs exits with
    any other code, run the hub again, now on this code. A hub stopped on purpose is left stopped."""

    def __init__(self, first, env=None):
        self.env = env
        self.procs = [first]
        self.codes: list[int] = []
        self.over = threading.Event()        # the test has ended: the hub it runs is stopped, not crashed
        self._t = threading.Thread(target=self._watch, daemon=True)
        self._t.start()

    def _watch(self):
        code = self.procs[-1].wait()
        self.codes.append(code)
        if code != server.EXIT_STOPPED and not self.over.is_set():
            self.procs.append(start_hub("service", self.env))

    def stop(self):
        self.over.set()                      # from here a hub that ends is stopped, not crashed
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        self._t.join(timeout=30)
        for p in self.procs:                 # one that the watch started just before `over` was set
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=30)


@pytest.fixture
def procs():
    """What a test started, ended when it ends, a failed test too. A `Supervisor` is stopped before the
    hub it runs: that hub ends on a SIGTERM, which is a crash to it, and it started a new one after the
    test was over."""
    made = []
    yield made
    supervisors = [p for p in made if isinstance(p, Supervisor)]
    for s in supervisors:
        s.stop()
    for p in made:
        if p not in supervisors:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=30)
    server.pid_file().unlink(missing_ok=True)


def wait_health(port, version=None, boot_not=None, seconds=10):
    c = hubclient.client()
    deadline = time.time() + seconds
    while time.time() < deadline:
        got = c.challenge()
        if got and (version is None or got["version"] == version) and got["boot"] != boot_not:
            return got
        time.sleep(0.05)
    pytest.fail(f"no hub on {version or 'any version'}")


def test_a_supervisor_that_is_stopped_starts_nothing_for_the_hub_it_sees_end(port, procs):
    """A failed test ends the hub it ran with a SIGTERM, which is a failure to the supervisor, and it
    started the next one after the test."""
    first = subprocess.Popen(["sleep", "300"])
    procs.append(first)
    sup = Supervisor(first)
    sup.stop()
    assert sup.codes == [-signal.SIGTERM] and sup.procs == [first]


# ── comparing versions ───────────────────────────────────────────────────────

@pytest.mark.parametrize("a, b, want", [
    ("1.0.10", "1.0.9", 1), ("1.0.9", "1.0.10", -1), ("2.0.0", "1.99.99", 1),
    ("1.0.0", "1.0.0", 0), ("1.0", "1.0.0", 0),
    ("1.0.0", "1.0.0.dev0", 1), ("1.0.0.dev0", "1.0.0", -1), ("1.0.0.dev0", "1.0.0.dev0", 0),
    ("1.0.1.dev0", "1.0.0", 1),
    ("banana", "1.0.0", None), ("1.0.0", None, None), ("", "1.0.0", None),
])
def test_versions_compare_as_numbers_and_a_development_build_is_older_than_its_release(a, b, want):
    assert hubclient.compare_versions(a, b) == want


# ── the hub's exit code (14.4) ───────────────────────────────────────────────

def test_an_upgrade_stop_under_the_service_exits_75_and_the_supervisor_starts_the_new_code(port, procs):
    old = start_old_hub("service")
    sup = Supervisor(old)
    procs.extend([old, sup])
    old_hub = wait_health(port, OLD)
    assert old_hub["service"] is True
    out, err = [], []
    c, started = hubclient.ensure_hub("cli", out.append, err.append)
    new_hub = c.challenge()
    assert new_hub["version"] == __version__ and new_hub["service"] is True
    assert new_hub["boot"] != old_hub["boot"]
    assert sup.codes == [75]
    assert err == [] and out == []
    exits = hub_rows("hub-exit")
    assert [(r["boot"], r["reason"]) for r in exits] == [(old_hub["boot"], "upgrade")]
    assert hub_rows("unclean-exit") == []                  # the old hub's exit row was written first
    procs.extend(sup.procs[1:])
    c.call("POST", "/_/stop", {"reason": "stop"})
    sup.stop()


def test_an_upgrade_stop_of_a_hub_the_service_did_not_start_exits_0_and_the_command_starts_the_new_one(port, procs):
    old = start_old_hub("cli")
    procs.append(old)
    old_hub = wait_health(port, OLD)
    assert old_hub["service"] is False
    c, started = hubclient.ensure_hub("cli", lambda s: None, lambda s: None)
    assert old.wait(timeout=30) == 0 and started is True
    new_hub = c.challenge()
    assert new_hub["version"] == __version__ and new_hub["boot"] != old_hub["boot"]
    starts = hub_rows("hub-start")
    assert [(r["version"], r["started_by"]) for r in starts] == [(OLD, "cli"), (__version__, "upgrade")]
    assert [(r["boot"], r["reason"]) for r in hub_rows("hub-exit")] == [(old_hub["boot"], "upgrade")]
    assert hub_rows("unclean-exit") == []
    info = server.read_pid_file()
    procs.append(_Adopted(info["pid"]))


def test_an_upgrade_waits_for_the_new_hub_while_it_listens_and_does_not_answer_yet(port, procs, monkeypatch):
    """The new hub listens from its bind on and answers once it serves; the wait for the new version took
    that silence for a hub that does not answer."""
    old = start_old_hub("cli")
    procs.append(old)
    old_hub = wait_health(port, OLD)
    usual = hubclient.TIMEOUT

    def spawn_late(who):
        monkeypatch.setattr(hubclient, "TIMEOUT", 0.5)      # only the wait for the new hub is short
        start_late_hub(who, late_by=2.0)

    monkeypatch.setattr(hubclient, "spawn_hub", spawn_late)
    c, started = hubclient.ensure_hub("cli", lambda s: None, lambda s: None)
    monkeypatch.setattr(hubclient, "TIMEOUT", usual)
    assert old.wait(timeout=30) == 0 and started is True
    new_hub = c.challenge()
    assert new_hub["version"] == __version__ and new_hub["boot"] != old_hub["boot"]


class _Adopted:
    """A hub that a command started detached: not our child, so stopped by pid."""

    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        return None if not gone(self.pid) else 0

    def terminate(self):
        import os
        import signal
        try:
            os.kill(self.pid, signal.SIGTERM)
        except OSError:
            pass

    def wait(self, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline and not gone(self.pid):
            time.sleep(0.05)


def test_a_hub_that_does_not_come_back_on_the_new_version_fails_with_the_diagnostics_hint(port, procs, monkeypatch):
    monkeypatch.setattr(hubclient, "UPGRADE_WAIT", 1.0)
    old = start_old_hub("service")             # no supervisor: nothing starts the new code
    procs.append(old)
    wait_health(port, OLD)
    with pytest.raises(hubclient.HubDidNotStart, match="sheaf diag"):
        hubclient.ensure_hub("cli", lambda s: None, lambda s: None)
    assert old.wait(timeout=30) == 75


def service_hub(port):
    return Hub(port=port, key=paths.ensure_key(), started_by="service", service=True)


def test_an_upgrade_stop_alone_of_a_service_hub_exits_75(port, work):
    hub = service_hub(port)
    assert hub.request_stop("upgrade") is True
    assert server.exit_code(hub) == server.EXIT_UPGRADE


@pytest.mark.parametrize("first, code", [("stop", server.EXIT_STOPPED), ("signal", 0)])
def test_a_stop_that_was_under_way_when_an_upgrade_stop_came_keeps_its_own_exit(port, work, monkeypatch, first, code):
    """The stop stays a stop: the service leaves it stopped. The signal stays a signal: `systemctl stop`
    is never restarted, and any other signal is (#79)."""
    monkeypatch.setenv(service.STOP_EXIT_ENV, str(server.EXIT_STOPPED))
    hub = service_hub(port)
    hub.request_stop(first)
    assert hub.request_stop("upgrade") is True
    assert hub.stop_requested == first and server.exit_code(hub) == code


# ── a deliberate stop under the unit of 14.3 has its own exit, which the unit does not restart (#79) ──

def test_a_deliberate_stop_of_a_service_hub_under_the_unit_exits_with_its_own_code(port, work, monkeypatch):
    monkeypatch.setenv(service.STOP_EXIT_ENV, str(server.EXIT_STOPPED))
    hub = service_hub(port)
    hub.request_stop("stop")
    assert server.exit_code(hub) == server.EXIT_STOPPED


def test_a_signal_that_comes_after_a_deliberate_stop_keeps_the_stop(port, work, monkeypatch):
    """Under Restart=always a signal exits 0 and is restarted: one that lands while the hub ends a
    `sheaf stop` must not bring back the hub the person stopped (gate P3)."""
    monkeypatch.setenv(service.STOP_EXIT_ENV, str(server.EXIT_STOPPED))
    hub = service_hub(port)
    seen = []
    hub.on_stop = seen.append
    hub.request_stop("stop")
    assert hub.request_stop("signal") is True
    assert hub.stop_requested == "stop" and seen == ["stop"]
    assert server.exit_code(hub) == server.EXIT_STOPPED


def test_a_stop_that_comes_after_a_signal_keeps_the_signal(port, work, monkeypatch):
    """The other way round the hub is ending on the signal already; the stop changes nothing."""
    monkeypatch.setenv(service.STOP_EXIT_ENV, str(server.EXIT_STOPPED))
    hub = service_hub(port)
    hub.request_stop("signal")
    hub.request_stop("stop")
    assert hub.stop_requested == "signal" and server.exit_code(hub) == 0


def test_a_signal_to_a_service_hub_exits_0_so_restart_always_starts_it_again(port, work, monkeypatch):
    monkeypatch.setenv(service.STOP_EXIT_ENV, str(server.EXIT_STOPPED))
    hub = service_hub(port)
    hub.request_stop("signal")
    assert server.exit_code(hub) == 0


@pytest.mark.parametrize("said", [None, "", "1", "75", "0"])
def test_a_deliberate_stop_under_a_unit_that_does_not_say_the_code_exits_0(port, work, monkeypatch, said):
    """A unit of an older sheaf (`Restart=on-failure`) would restart a 3, and launchd's
    `KeepAlive {SuccessfulExit: false}` restarts every exit but 0: neither carries the line, so the
    stop exits 0 there, which both leave down. Only the code the unit names is taken."""
    if said is None:
        monkeypatch.delenv(service.STOP_EXIT_ENV, raising=False)
    else:
        monkeypatch.setenv(service.STOP_EXIT_ENV, said)
    hub = service_hub(port)
    hub.request_stop("stop")
    assert server.exit_code(hub) == 0


def test_a_deliberate_stop_of_a_hub_the_service_did_not_start_exits_0(port, work, monkeypatch):
    monkeypatch.setenv(service.STOP_EXIT_ENV, str(server.EXIT_STOPPED))
    hub = Hub(port=port, key=paths.ensure_key(), started_by="cli", service=False)
    hub.request_stop("stop")
    assert server.exit_code(hub) == 0


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="systemd's rule: Linux")
def test_sheaf_stop_of_a_service_hub_exits_stopped_and_the_supervisor_leaves_it_down(port, procs):
    hub = start_hub("service", unit_env())
    sup = Supervisor(hub, unit_env())
    procs.extend([hub, sup])
    wait_health(port)
    assert cli.main(["stop"]) == 0
    assert hub.wait(timeout=30) == server.EXIT_STOPPED
    time.sleep(0.5)
    assert sup.codes == [server.EXIT_STOPPED] and sup.procs == [hub]
    assert [r["reason"] for r in hub_rows("hub-exit")] == ["stop"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="systemd's rule: Linux")
def test_a_stray_sigterm_to_a_service_hub_is_restarted(port, procs):
    """2026-10-30 on tiroir-tt: a signal from a sender nobody knows stopped the hub, it exited 0 and
    Restart=on-failure left it down."""
    hub = start_hub("service", unit_env())
    sup = Supervisor(hub, unit_env())
    procs.extend([hub, sup])
    first = wait_health(port)
    hub.send_signal(signal.SIGTERM)
    assert hub.wait(timeout=30) == 0
    again = wait_health(port, boot_not=first["boot"], seconds=20)
    procs.extend(sup.procs[1:])
    assert again["service"] is True and sup.codes == [0]


def test_a_stop_that_comes_while_an_upgrade_stop_is_being_taken_is_not_overwritten_by_it(port, work, monkeypatch):
    """The upgrade stop has looked at `stop_requested` and is in the busy check when a stop comes
    from another thread (a request, or the signal handler): the stop waits for it, and ends the
    hub for good after it. Without one lock for both the later write would be the upgrade's."""
    monkeypatch.setenv(service.STOP_EXIT_ENV, str(server.EXIT_STOPPED))
    hub = service_hub(port)
    seen = []
    hub.on_stop = seen.append
    other = threading.Thread(target=hub.request_stop, args=("stop",))
    real_busy = hub.busy

    def busy():
        other.start()
        other.join(0.5)                # without the lock this thread is done by now
        return real_busy()
    hub.busy = busy
    assert hub.request_stop("upgrade", force=False) is True
    other.join(5)
    assert hub.stop_requested == "stop" and seen == ["upgrade", "stop"]
    assert server.exit_code(hub) == server.EXIT_STOPPED


def test_a_second_signal_that_interrupts_the_first_inside_the_admit_lock_does_not_hang_the_hub(port, work):
    """The signal handler runs in the main thread, between two of its instructions, and a second
    SIGTERM can interrupt it while it holds `admit`: the same thread asks for the lock again."""
    hub = service_hub(port)
    done = []

    def second_signal_inside_the_first():
        with hub.admit:
            hub.request_stop("upgrade")
        done.append(True)
    t = threading.Thread(target=second_signal_inside_the_first, daemon=True)
    t.start()
    t.join(3)
    assert done == [True] and hub.stop_requested == "upgrade"


# ── the cases that leave the hub alone ───────────────────────────────────────

@pytest.fixture
def thread_hub(port, work):
    made = []

    def start(version):
        sock = server.bind(port)
        hub = Hub(port=port, key=paths.ensure_key(), started_by="test", version=version)
        srv = server.HubServer(hub, sock)
        srv.start()
        made.append(srv)
        return hub
    yield start
    for srv in made:
        srv.close()


def test_a_newer_command_with_a_job_running_says_so_and_uses_the_running_hub(port, thread_hub):
    hub = thread_hub(OLD)
    hub.jobs = lambda: {"asking": [], "telling": [["work/plan.md", "c1"]]}
    out, err = [], []
    c, started = hubclient.ensure_hub("cli", out.append, err.append)
    assert err == [f"  ! the hub runs {OLD} and an Ask or Tell is running; this is {__version__}. "
                   "Run sheaf restart when it is done."]
    assert started is False and c.challenge()["boot"] == hub.boot
    assert not hub.stop_requested


def test_an_ask_that_starts_between_the_idle_check_and_the_stop_is_not_killed_by_the_upgrade(
        port, thread_hub):
    hub = thread_hub(OLD)
    asked = []

    def jobs():                          # idle when the command looks, busy when it posts the stop
        asked.append(1)
        busy = len(asked) > 1
        return {"asking": [["work/plan.md", "c1"]] if busy else [], "telling": []}
    hub.jobs = jobs
    out, err = [], []
    c, started = hubclient.ensure_hub("cli", out.append, err.append)
    assert err == [f"  ! the hub runs {OLD} and an Ask or Tell is running; this is {__version__}. "
                   "Run sheaf restart when it is done."]
    assert started is False and c.challenge()["boot"] == hub.boot
    assert not hub.stop_requested


def test_an_older_command_says_so_and_uses_the_running_hub(port, thread_hub):
    hub = thread_hub("99.0.0")
    out, err = [], []
    c, started = hubclient.ensure_hub("cli", out.append, err.append)
    assert err == [f"  ! the hub runs 99.0.0, this is {__version__}"]
    assert started is False and c.challenge()["boot"] == hub.boot and not hub.stop_requested


def test_a_version_that_cannot_be_read_is_said_and_the_hub_is_left_alone(port, thread_hub):
    hub = thread_hub("banana")
    out, err = [], []
    hubclient.ensure_hub("cli", out.append, err.append)
    assert err == [f"  ! the hub runs banana, this is {__version__}"] and not hub.stop_requested


def test_the_same_version_says_nothing(port, thread_hub):
    thread_hub(__version__)
    out, err = [], []
    hubclient.ensure_hub("cli", out.append, err.append)
    assert out == [] and err == []


def test_a_hub_that_will_not_say_whether_a_job_runs_is_not_restarted(port, thread_hub, monkeypatch):
    hub = thread_hub(OLD)
    real = hubclient.HubClient.call

    def call(self, method, path, body=None):
        if path == "/_/jobs":
            return 500, {"ok": False}
        return real(self, method, path, body)
    monkeypatch.setattr(hubclient.HubClient, "call", call)
    out, err = [], []
    hubclient.ensure_hub("cli", out.append, err.append)
    assert err == [f"  ! the hub runs {OLD}, this is {__version__}"] and not hub.stop_requested


# ── a stop that does not finish says what was still there ────────────────────

@pytest.fixture
def quick_stop(monkeypatch):
    monkeypatch.setattr(hubclient, "STOP_WAIT", 0.3)


def stub_the_stop(monkeypatch, after, status=200):
    """The hub answers the stop with `status`; what `challenge()` says from then on is `after` of its answer."""
    real_call, real_challenge, posted = hubclient.HubClient.call, hubclient.HubClient.challenge, []

    def call(self, method, path, body=None):
        if path == "/_/stop":
            posted.append(body)
            return status, {"ok": status == 200}
        return real_call(self, method, path, body)

    def challenge(self):
        got = real_challenge(self)
        return after(got) if posted else got
    monkeypatch.setattr(hubclient.HubClient, "call", call)
    monkeypatch.setattr(hubclient.HubClient, "challenge", challenge)


def test_an_upgrade_stop_that_leaves_the_hub_answering_says_so(port, thread_hub, quick_stop, monkeypatch):
    thread_hub(OLD)
    stub_the_stop(monkeypatch, lambda got: got)           # takes the stop and goes on serving
    with pytest.raises(hubclient.HubDidNotStart) as e:
        hubclient.ensure_hub("cli", lambda s: None, lambda s: None)
    assert str(e.value) == "the hub did not stop for the upgrade (still answering; see `sheaf diag`)"


@pytest.mark.parametrize("after, said", [
    (lambda got: None, "process {pid} is still running"),
    (lambda got: {**got, "boot": "another-boot"}, "another hub answers and process {pid} is still running"),
])
def test_an_upgrade_stop_names_the_process_that_is_still_there(
        port, thread_hub, procs, quick_stop, monkeypatch, after, said):
    hub = thread_hub(OLD)
    left = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    procs.append(left)
    state.write_json(server.pid_file(), {"pid": left.pid, "boot": hub.boot})
    stub_the_stop(monkeypatch, after)
    with pytest.raises(hubclient.HubDidNotStart) as e:
        hubclient.ensure_hub("cli", lambda s: None, lambda s: None)
    assert str(e.value) == (f"the hub did not stop for the upgrade ({said.format(pid=left.pid)}; "
                            "see `sheaf diag`)")


def test_an_upgrade_stop_the_hub_refuses_says_so(port, thread_hub, quick_stop, monkeypatch):
    thread_hub(OLD)
    stub_the_stop(monkeypatch, lambda got: got, status=500)
    with pytest.raises(hubclient.HubDidNotStart) as e:
        hubclient.ensure_hub("cli", lambda s: None, lambda s: None)
    assert str(e.value) == "the hub did not stop for the upgrade (it refused the stop; see `sheaf diag`)"


# ── how long a command waits for a stop (8.10: a hub stop waits out the grace of its jobs) ─────

def test_the_wait_for_a_stop_outlasts_what_a_child_that_ignores_sigterm_makes_the_hub_take():
    """A hub stop gives a child that ignores SIGTERM TERM_GRACE seconds, kills it, and gives it one
    second more (`Jobs.kill_all`) before the hub writes its exit row. A command that stopped waiting
    at TERM_GRACE would say "still running" a moment before the hub ended, and exit 1."""
    assert hubclient.STOP_WAIT > jobs.TERM_GRACE + 1


def test_sheaf_stop_waits_as_long_as_every_other_stop_does(port, thread_hub, quick_stop, monkeypatch, capsys):
    thread_hub(__version__)
    stub_the_stop(monkeypatch, lambda got: got)           # takes the stop and goes on serving
    began = time.monotonic()
    assert cli.cmd_stop([]) == 1
    assert time.monotonic() - began < 3                  # it waited STOP_WAIT, 0.3 s here, not a number of its own
    assert capsys.readouterr().err == "sheaf: the hub is still running after 0.3 s\n"
