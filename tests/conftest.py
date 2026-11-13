import faulthandler
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

import pytest

import sheafmd

pytest_plugins = ["driver_stall"]     # the first page test to time out in the Playwright driver ends the run

# Before anything else imports sheafmd's parts: another checkout's venv resolves it to that checkout, and the run
# would be about code that is not here. tests/test_import_guard.py says why this refuses.
_OWN_SOURCE = Path(__file__).resolve().parents[1] / "src"
if not Path(sheafmd.__file__).resolve().is_relative_to(_OWN_SOURCE):
    raise pytest.UsageError(f"this suite imports {sheafmd.__file__}, not the code under {_OWN_SOURCE}. "
                            f"Run it with PYTHONPATH={_OWN_SOURCE}")

from helpers import NOW, PLAN, Opener, browser_on, claim_port, proc_state, stop_hub
# no_process_left_behind and the_test_that_is_running are the fixtures of tests/leakguard.py
from leakguard import NODE_VAR, RUN_VAR, no_process_left_behind, stop_left, the_test_that_is_running  # noqa: F401
from sheafmd import config
from sheafmd.agents.detect import TABLE
from sheafmd.cli import main
from sheafmd.hub import recover
from sheafmd.hub.client import _AGENT_ENV_PREFIXES as AGENT_ENV_PREFIXES
from sheafmd.hub.server import read_pid_file
from sheafmd.seat import SSH_VARS


def pytest_sessionstart(session):
    """Under tools/ci/stall_watch.py: write this process's pid where the watcher
    looks, and answer SIGUSR2 with the main thread's Python stack and SIGUSR1 with every thread's,
    written by faulthandler's C handler
    (so it works with the GIL held or the main thread stuck) to the file the watcher named. Pytest's
    own capture has replaced fd 2 by now, which is why the stacks go to a file."""
    # popped, so that a pytest run started by a test (test_hub_sock, test_leakguard) does not inherit
    # the names and overwrite the outer run's pid
    pidfile, dump = os.environ.pop("SHEAF_PYTEST_PIDFILE", None), os.environ.pop("SHEAF_STALL_DUMP", None)
    if pidfile and dump and hasattr(signal, "SIGUSR1"):
        Path(pidfile).write_text(str(os.getpid()))
        out = open(dump, "a")
        faulthandler.register(signal.SIGUSR1, file=out, all_threads=True)
        # faulthandler dumps at most 100 threads, newest first, so with 100 leaked threads the main
        # thread is the one it leaves out. The watcher signals the main thread with this one first.
        faulthandler.register(signal.SIGUSR2, file=out, all_threads=False)


MAIN_STACK_AT = 0.9     # of pytest-timeout's limit: when the main thread's own stack is written


@pytest.fixture(autouse=True)
def the_main_thread_names_its_frame(request):
    """Write the main thread's stack to stderr at 90% of the test's timeout (setup, call and teardown
    together), so a hang names the call it stands in. pytest-timeout prints every thread but the one it
    interrupts, and faulthandler's dump of every thread stops at 100, newest first, which leaves out
    the main thread, the oldest, of a run that leaked threads: CI, PR 227, 3,900 of them. This one is
    a thread of its own that reads the main thread's frame, so it speaks with the main thread stuck in
    a Playwright wait too. The test goes on; the timeout still ends it."""
    config = request.config
    if not config.pluginmanager.hasplugin("timeout"):     # -p no:timeout: nothing ends a test, nothing to announce
        yield
        return
    limit = config.getoption("timeout", None)       # --timeout, even 0, wins over the ini value
    limit = float(config.getini("timeout") or 0) if limit is None else float(limit)
    mark = request.node.get_closest_marker("timeout")
    if mark and mark.args:
        limit = float(mark.args[0])
    if limit <= 0:
        yield
        return
    main = threading.main_thread().ident

    def speak():
        frame = sys._current_frames().get(main)
        if frame is None:
            return
        text = f"\n--- {request.node.nodeid}: still running after {limit * MAIN_STACK_AT:.0f} s; the main thread is in:\n"
        text += "".join(traceback.format_stack(frame)) + "---\n"
        capture = request.config.pluginmanager.getplugin("capturemanager")
        with capture.global_and_fixture_disabled():
            sys.stderr.write(text)
            sys.stderr.flush()

    timer = threading.Timer(limit * MAIN_STACK_AT, speak)
    timer.daemon = True
    timer.start()
    yield
    timer.cancel()
    timer.join()


def pytest_configure(config):
    """`-n` spreads tests with `--dist load` unless the run says otherwise; `loadgroup` keeps a file with
    IN_ORDER = True on one worker (pytest_itemcollected) and spreads the rest as before. Not in `addopts`:
    `--dist` belongs to the xdist plugin, and a run without it (`-p no:xdist`) would not start. A worker
    reads its own `loadgroup` from the arguments it was started with, which do not have the change."""
    if not config.pluginmanager.hasplugin("xdist"):
        return
    if hasattr(config, "workerinput"):
        config.option.loadgroup = True
    elif config.getoption("dist") == "load":
        config.option.dist = "loadgroup"


def pytest_itemcollected(item):
    """Under xdist (`--dist loadgroup`, pytest_configure above) a file with IN_ORDER = True runs on one worker: its
    tests share a module list, which a second worker does not have. xdist reads the group while it sorts the
    items, so the mark goes on as each one is collected."""
    if getattr(item.module, "IN_ORDER", False):
        item.add_marker(pytest.mark.xdist_group(item.module.__name__))


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """SHEAF_TEST_SLICE=i/n keeps the i-th of every n tests that are left after -m: ci.yml runs each
    Python as three jobs, one slice each. A file with IN_ORDER = True, whose tests read what the test
    before them left, counts as one test and stays whole in one slice. Every xdist worker collects the
    same tests in the same order, so each keeps the same slice."""
    slice_ = os.environ.get("SHEAF_TEST_SLICE")
    if not slice_:
        return
    i, n = (int(x) for x in slice_.split("/"))
    units, whole = [], {}
    for it in items:
        if getattr(it.module, "IN_ORDER", False):
            if it.module not in whole:
                whole[it.module] = []
                units.append(whole[it.module])
            whole[it.module].append(it)
        else:
            units.append([it])
    keep = [it for k, u in enumerate(units) if k % n == i - 1 for it in u]
    kept = set(keep)
    config.hook.pytest_deselected(items=[it for it in items if it not in kept])
    items[:] = keep


@pytest.fixture(autouse=True)
def sheaf_env(tmp_path, monkeypatch, request):
    """Every test gets its own state, config, cache and runtime folders, its own
    home and its own temp dir (the legacy lock folder lives in the temp dir), so no
    test reads or writes the real ones, or another test's locks. Subprocesses
    inherit the environment."""
    # The runtime folder holds the hub's socket, and a socket path holds 108 characters: under a long
    # --basetemp, tmp_path is too deep for it. A folder of its own under /tmp is short, whatever the
    # basetemp, and mkdtemp makes it 0700.
    run = Path(tempfile.mkdtemp(prefix="sh-", dir="/tmp"))
    request.addfinalizer(lambda: shutil.rmtree(run, ignore_errors=True))
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    monkeypatch.setenv("SHEAF_HOME", str(tmp_path / "sheaf-home"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("TMPDIR", str(tmp))
    # The byline and the comment author: never the login name of whoever runs the suite.
    monkeypatch.setenv("SHEAF_NAME", "Ada")
    # No agent is detected unless a test says so, whichever agent runs the suite.
    agent_vars = [var for agent in TABLE for var, _ in agent.present_when]
    # Every variable of the agent that runs the suite goes, not only the ones that make it
    # present: its message socket and its command would be recorded in a test's own state.
    prefixed = [k for k in os.environ if k.startswith(AGENT_ENV_PREFIXES)]
    # A suite run over ssh is not a remote seat: `sheaf open` opens the (stand-in) browser.
    for var in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", *SSH_VARS, *agent_vars, *prefixed):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp))
    # a pytest run that a test starts runs all of its own tests, not a slice of them
    monkeypatch.delenv("SHEAF_TEST_SLICE", raising=False)


@pytest.fixture(autouse=True)
def no_real_sockets_folder(tmp_path, monkeypatch):
    """Where Claude Code's own sockets live, `/run/user/<uid>/cc-socks`, is the test's own empty
    folder: detection looks for a socket there by pid and must never look at the real ones."""
    monkeypatch.setattr("sheafmd.agents.claude_code.SOCKS_ROOT", tmp_path / "cc-run")


@pytest.fixture(autouse=True)
def port(sheaf_env, monkeypatch):
    """A free port of this test's own, held until the test ends (helpers.claim_port): a hub that a
    command starts never lands on 27419, which is the port of the hub of whoever runs the suite, and
    no other process is handed this one in the gap before the hub binds it."""
    p, release = claim_port()
    monkeypatch.setenv("SHEAF_PORT", str(p))
    assert p != config.DEFAULT_PORT and config.port() == p        # what every command of the test resolves to
    yield p
    release()


@pytest.fixture(autouse=True)
def nothing_reaches_the_default_port(monkeypatch):
    """A test never connects to 27419 or binds it, whatever it did to SHEAF_PORT: that is the port of
    the hub of whoever runs the suite (a hub of the suite once held it). A process of the
    test is held to the same by `spawned`."""
    def watched(real):
        def guarded(self, address, *rest):
            if isinstance(address, tuple) and len(address) >= 2 and address[1] == config.DEFAULT_PORT:
                raise AssertionError(f"a test reached port {config.DEFAULT_PORT}, the port of the hub of "
                                     "whoever runs the suite; the `port` fixture gives each test its own")
            return real(self, address, *rest)
        return guarded
    for name in ("connect", "connect_ex", "bind"):
        monkeypatch.setattr(socket.socket, name, watched(getattr(socket.socket, name)))


def _words(args) -> list[str]:
    return [str(a) for a in args] if isinstance(args, (list, tuple)) else [str(args)]


def _is_hub_command(args) -> bool:
    words = _words(args)
    return any(words[i:i + 3] == ["-m", "sheafmd", "hub"] for i in range(len(words)))


def _runs_sheaf(args) -> bool:
    words = _words(args)
    return any("sheafmd" in w for w in words) or os.path.basename(words[0]) == "sheaf"


class Spawned:
    """What a test started with `subprocess`: every pid, in the order of the starts, and the ones that
    run a hub (`-m sheafmd hub`)."""

    def __init__(self):
        self.pids, self.hubs = [], []


@pytest.fixture(autouse=True)
def spawned(request, monkeypatch):
    """Every process this test starts with `subprocess` (a command's detached hub, a test's own
    `Popen`, `subprocess.run`), by whichever path. Each carries the run and this test in its environment
    whatever `env` the test gave it, which is how `reap` and the guard find it (tests/leakguard.py), and
    one that runs sheaf is refused when the environment it would have leads it to the default port."""
    made = Spawned()
    real = subprocess.Popen
    marks = {RUN_VAR: os.environ[RUN_VAR], NODE_VAR: request.node.nodeid}

    def port_of(env):
        """What `config.port()` answers in `env`: its SHEAF_PORT, else the `port =` of the config file under
        the home it has. The second is asked of a process of its own, so that nothing in this one is changed."""
        v = env.get("SHEAF_PORT", "").strip()
        if v.isascii() and v.isdigit():
            return int(v)
        ask = real([sys.executable, "-c", "from sheafmd import config; print(config.port())"],
                   env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            out = ask.communicate(timeout=60)[0].strip()
        except subprocess.TimeoutExpired:
            ask.kill()
            ask.wait()
            raise
        return int(out) if out.isdigit() else None               # a config that does not parse stops nothing here

    class Tracked(real):
        def __init__(self, args, *a, **k):                       # `env` is passed by name, as every test does
            if k.get("env") is not None:
                k["env"] = {**marks, **k["env"]}
            env = k["env"] if k.get("env") is not None else os.environ
            if _runs_sheaf(args) and port_of(env) == config.DEFAULT_PORT:
                raise AssertionError(f"{args!r} would run on port {config.DEFAULT_PORT}, the port of the hub "
                                     "of whoever runs the suite; SHEAF_PORT or a `port =` of the test's own is missing")
            super().__init__(args, *a, **k)
            made.pids.append(self.pid)
            if _is_hub_command(args):
                made.hubs.append(self.pid)

    monkeypatch.setattr(subprocess, "Popen", Tracked)
    return made


@pytest.fixture(autouse=True)
def reap(request, port, spawned):
    """Whatever a test left running is stopped when it ends: the hub in its pid file, the hubs it
    started itself, and then every other process that carries this test's mark (tests/leakguard.py), which
    is how a hub that a shell script started (the fake service manager), one that was still starting
    and had no pid file yet, and a child behind a `sh -c` are found. A run that fails or is stopped
    runs this too."""
    yield
    info = read_pid_file()
    if info:
        stop_hub(info["pid"])
    for pid in spawned.hubs:
        stop_hub(pid)
    if spawned.pids:                                    # a look at /proc takes 20 ms: only where one was started
        stop_left(os.environ[RUN_VAR], request.node.nodeid)


@pytest.fixture
def sent(monkeypatch):
    """Every signal `hub.recover` sends to a hub that does not answer: (seconds on the monotonic
    clock, pid, signal, whether the process still ran when it was sent). A test that expects none
    asserts it is empty."""
    log = []
    real = recover.HubProcess.send

    def spy(self, sig):
        log.append((time.monotonic(), self.pid, sig, proc_state(self.pid) == "alive"))
        return real(self, sig)
    monkeypatch.setattr(recover.HubProcess, "send", spy)
    return log


class Ran:
    def __init__(self, code, out, err):
        self.code, self.out, self.err = code, out, err


@pytest.fixture
def sheaf(capsys):
    """Run `main` in this process: sheaf(arg, ...) -> Ran(code, out, err)."""
    def run(*argv):
        code = main([str(a) for a in argv])
        out, err = capsys.readouterr()
        return Ran(code, out, err)
    return run


@pytest.fixture
def closed():
    """chmod 000 on the folders a test names, and back to normal when it ends (pytest has to remove
    them). Root enters any folder, so a test that uses it is skipped when run as root."""
    if os.geteuid() == 0:
        pytest.skip("root enters any folder")
    shut = []

    def close(folder):
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o000)
        shut.append(folder)
    yield close
    for folder in shut:
        folder.chmod(0o700)


@pytest.fixture
def work(tmp_path):
    """The folder the documents live in. Outside git, so it is its own root."""
    w = tmp_path / "work"
    w.mkdir()
    return w


@pytest.fixture
def short_tmp(monkeypatch):
    """Chrome keeps a unix socket under TMPDIR and fails with "Socket path too long" when
    that is deep; the suite's own temp dir inside tmp_path is. A short one for Chrome."""
    d = tempfile.mkdtemp(dir="/tmp")
    monkeypatch.setenv("TMPDIR", d)
    monkeypatch.setattr(tempfile, "tempdir", d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


# ── the hub, in memory ───────────────────────────────────────────────────────

HUB_PORT = 27419


@pytest.fixture
def hub(work):
    from sheafmd import paths
    from sheafmd.hub.core import Hub
    h = Hub(port=HUB_PORT, key=paths.ensure_key(), started_by="test")
    yield h
    # A push the test left due ends here, in this test's state: its pusher is a thread that outlives the test and
    # writes its `push-failed` row into the state of whichever test runs next (#32).
    assert h.commits.settle(30), "the hub's pusher did not finish within 30 s of the test's end"


@pytest.fixture
def browser(hub):
    """The handler with no socket behind it (`browser_on`)."""
    return browser_on(hub)


@pytest.fixture
def opened_browser(monkeypatch):
    """`webbrowser.open` replaced by an `Opener`: what `sheaf open` asked to open is in `.opened`."""
    b = Opener()
    monkeypatch.setattr("sheafmd.cli.webbrowser.open", b)
    return b


@pytest.fixture
def plan(work, hub):
    """A document outside git, so its folder is its root: address `work/plan.md`. Its root is
    registered, as `sheaf open` does by rendering it."""
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    hub.roots.for_document(f)
    return f


@pytest.fixture
def put(work):
    """Write a document of the folder `work`; `age` is how many seconds old its file is."""
    def put(name, text=PLAN, age=0):
        f = work / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        os.utime(f, (NOW - age, NOW - age))
        return f
    return put


@pytest.fixture
def world(browser, put, work, monkeypatch):
    """The hub with one root, `work`, holding `start.md`. Its clock stands at NOW, the time the
    documents' ages are counted from, so "4 min ago" does not depend on how long the suite ran. A
    sweep of the index that a tick makes due runs inside that tick, not on a thread of its own, so a
    test that ticks by hand has been told everything when the tick returns."""
    browser.hub.clock = lambda: NOW
    monkeypatch.setattr(browser.hub.index, "_start_sweep", lambda run: run())
    put("start.md")
    browser.hub.roots.for_document(work / "start.md")
    return browser


# ── proxy mode, in memory (SPEC 9.9) ─────────────────────────────────────────

@pytest.fixture
def other(tmp_path):
    """A folder of documents that is no root of Bea's: Cal's."""
    o = tmp_path / "other"
    o.mkdir()
    return o


@pytest.fixture
def front(hub, work, other, browser):
    """The hub in proxy mode, and the proxy in front of it: Bea's roots are `work`, Cal's
    `other`. `front.hub` is `browser.hub`, so a test can compare the two listeners. The proxy is set after the hub
    is built, so no private root is registered here: a test that needs one builds its hub from `two_roots`."""
    import pwd
    from helpers import BEA, CAL, FRONT, Front
    from sheafmd.hub import proxy
    hub.proxy = proxy.parse({"origin": FRONT, "socket": "/run/sheaf-proxy/hub.sock",
                             "proxy_user": pwd.getpwuid(os.getuid()).pw_name,
                             "members": {BEA: {"name": "Bea", "roots": [str(work)]},
                                         CAL: {"name": "Cal", "roots": [str(other)]}}}, "the test")
    return Front(hub, browser.handler)


@pytest.fixture
def proxy_folder():
    """The proxy socket's folder as the deployment makes it: the hub's account's, the proxy's
    group (here the test's own), mode 2750. Under /tmp, so the socket's path stays short."""
    import pwd
    from pathlib import Path
    top = Path(tempfile.mkdtemp(dir="/tmp", prefix="sp-"))
    f = top / "s"
    f.mkdir()
    os.chown(f, -1, pwd.getpwuid(os.getuid()).pw_gid)
    os.chmod(f, 0o2750)
    yield f
    shutil.rmtree(top, ignore_errors=True)


@pytest.fixture
def proxy_served(front, plan, proxy_folder):
    """`front`'s hub served for real: on a port of its own and on a proxy socket in `proxy_folder`."""
    import dataclasses
    from sheafmd.hub import proxy, server
    hub = front.hub
    hub.proxy = dataclasses.replace(hub.proxy, socket=proxy_folder / "hub.sock")
    sock = server.bind(0)
    hub.port = sock.getsockname()[1]
    srv = server.HubServer(hub, sock, proxy.bind(hub.proxy))
    srv.start()
    yield hub
    srv.close()
