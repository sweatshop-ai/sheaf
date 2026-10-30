"""tools/ci/service_linux.py and service_macos.py install a REAL user service (SPEC 14.3) and
tools/wheel_smoke.py installs the built wheel. The services belong to a CI runner: this
laptop has the owner's real hub and units. So each service script refuses unless it is on a runner
(GITHUB_ACTIONS=true and the matching RUNNER_OS), before it touches anything, and these tests only
ever run it where it must refuse: on a PATH with no systemctl, launchctl, sudo or loginctl, with a
home of its own, so that even a script that did not refuse would have nothing to start."""
import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from helpers import proc_state
from sheafmd import signals

TOOLS = Path(__file__).resolve().parent.parent / "tools"
CI = TOOLS / "ci"
SERVICE_SCRIPTS = {"service_linux.py": "Linux", "service_macos.py": "macOS"}
SRC = TOOLS.parent / "src"


def load(name):
    spec = importlib.util.spec_from_file_location(name, CI / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(CI))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(CI))
    return mod


@pytest.fixture
def bare(tmp_path):
    """An environment in which nothing real can be reached."""
    home = tmp_path / "home"
    home.mkdir()
    empty = tmp_path / "empty-path"
    empty.mkdir()
    return {"PATH": str(empty), "HOME": str(home),
            "PYTHONPATH": str(SRC), "XDG_CONFIG_HOME": str(home / ".config"),
            "SHEAF_HOME": str(tmp_path / "sheaf-home")}


def run(script, env):
    return subprocess.run([sys.executable, str(CI / script)], env=env, capture_output=True,
                          text=True, timeout=60)


@pytest.mark.parametrize("script", SERVICE_SCRIPTS)
@pytest.mark.parametrize("extra", [
    {},
    {"GITHUB_ACTIONS": "false", "RUNNER_OS": "Linux"},
    {"GITHUB_ACTIONS": "true"},                      # a stray variable on a laptop is not a runner
    {"GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows"},
    {"RUNNER_OS": "Linux"},
    {"RUNNER_OS": "macOS"},
])
def test_a_service_script_refuses_where_it_is_not_on_a_runner_of_its_own_system(script, extra, bare):
    if extra.get("GITHUB_ACTIONS") == "true" and extra.get("RUNNER_OS") == SERVICE_SCRIPTS[script]:
        pytest.skip("that is a runner")
    done = run(script, {**bare, **extra})
    assert done.returncode == 2
    assert "refuses" in done.stderr and "GitHub Actions" in done.stderr
    assert done.stdout == ""
    assert list(Path(bare["HOME"]).iterdir()) == []
    assert not Path(bare["SHEAF_HOME"]).exists()


@pytest.mark.parametrize("script,other", [("service_linux.py", "macOS"), ("service_macos.py", "Linux")])
def test_a_runner_of_the_other_system_is_refused_too(script, other, bare):
    done = run(script, {**bare, "GITHUB_ACTIONS": "true", "RUNNER_OS": other})
    assert done.returncode == 2 and "refuses" in done.stderr


@pytest.mark.parametrize("script", SERVICE_SCRIPTS)
def test_the_refusal_is_the_first_thing_the_script_does(script):
    tree = ast.parse((CI / script).read_text(encoding="utf-8"))
    body = [n for n in tree.body
            if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant))
            and not isinstance(n, (ast.Import, ast.ImportFrom))]
    first = body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    call = ast.unparse(first.value)
    assert call == f"_ci.guard({SERVICE_SCRIPTS[script]!r})", call


@pytest.mark.parametrize("script", SERVICE_SCRIPTS)
def test_sheaf_is_imported_only_after_the_refusal(script):
    tree = ast.parse((CI / script).read_text(encoding="utf-8"))
    guard = next(i for i, n in enumerate(tree.body) if isinstance(n, ast.Expr) and "_ci.guard" in ast.unparse(n))
    before = [ast.unparse(n) for n in tree.body[:guard] if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not [i for i in before if "sheafmd" in i], before
    assert any("sheafmd" in ast.unparse(n) for n in tree.body[guard:] if isinstance(n, ast.ImportFrom))


def test_the_system_names_the_runner_sets_are_the_ones_the_guard_reads():
    # Each script is paired with the system its name says, spelt as GitHub spells RUNNER_OS ("macOS", not "MacOS").
    assert set(SERVICE_SCRIPTS.values()) == {"Linux", "macOS"}
    for script, system in SERVICE_SCRIPTS.items():
        assert script == f"service_{system.lower()}.py"
    assert sorted(p.name for p in CI.glob("*.py")) == sorted(["_ci.py", "page_paths.py", "stall_watch.py", *SERVICE_SCRIPTS])


# ── what the two scripts take from the library, and what they call things ────

def load_service_script(name, monkeypatch):
    """The script as a module, on a runner of its own system: importing it only runs the guard."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_OS", SERVICE_SCRIPTS[f"{name}.py"])
    monkeypatch.syspath_prepend(str(SRC))
    return load(name)


@pytest.mark.parametrize("name,copy", [("service_linux", "UNIT"), ("service_macos", "LABEL")])
def test_a_service_script_takes_the_unit_and_the_label_from_the_library(name, copy, monkeypatch):
    mod = load_service_script(name, monkeypatch)
    assert copy not in vars(mod), "the library's name is used, not a copy of it"


@pytest.mark.parametrize("script", SERVICE_SCRIPTS)
def test_a_service_script_asks_the_library_where_the_definition_file_is(script):
    # The checks look at the file `sheaf service install` wrote, at the place the library says;
    # a path built by hand here would agree with it only until the library changes.
    tree = ast.parse((CI / script).read_text(encoding="utf-8"))
    words = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not words & {".config", "systemd", "LaunchAgents", "Library", "sheaf.service"}, words
    ask = "unit_path" if script == "service_linux.py" else "plist_path"
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert ask in called


def test_the_names_say_what_the_functions_do(monkeypatch):
    linux = load_service_script("service_linux", monkeypatch)
    macos = load_service_script("service_macos", monkeypatch)
    # 'agent' is the coding agent (GLOSSARY); this is launchd's job
    assert hasattr(macos, "launchd_job") and not hasattr(macos, "agent")
    # `user_session()` sounded like a question; it sets variables and runs `sudo loginctl enable-linger`
    assert hasattr(linux, "enable_user_session") and not hasattr(linux, "user_session")
    # one idea, one name, on both systems
    assert hasattr(linux, "hub_back") and hasattr(macos, "hub_back") and not hasattr(macos, "back")


# ── the helpers the two scripts share ────────────────────────────────────────

def test_show_output_becomes_a_mapping():
    ci = load("_ci")
    text = "ActiveState=activating\nSubState=auto-restart\nResult=signal\nExecMainStatus=9\nNRestarts=1\n"
    got = ci.parse_show(text)
    assert got == {"ActiveState": "activating", "SubState": "auto-restart", "Result": "signal",
                   "ExecMainStatus": "9", "NRestarts": "1"}
    assert ci.parse_show("Description=a=b\n\nBlank\n") == {"Description": "a=b"}


def test_a_row_of_the_diagnostics_log_is_found_by_kind_and_fields():
    ci = load("_ci")
    rows = [{"kind": "hub-start"}, {"kind": "unclean-exit"}, {"kind": "hub-start"},
            {"kind": "hub-exit", "reason": "upgrade"}]
    assert ci.has_row(json.dumps(rows), "hub-exit", reason="upgrade")
    assert not ci.has_row(json.dumps(rows), "hub-exit", reason="stop")
    assert not ci.has_row("[]", "hub-exit")


def test_wait_until_returns_the_value_in_time_and_none_when_it_is_late():
    ci = load("_ci")
    calls = []

    def third_time():
        calls.append(1)
        return "ready" if len(calls) == 3 else None
    assert ci.wait_until(third_time, seconds=5, every=0.01) == "ready"
    assert ci.wait_until(lambda: None, seconds=0.1, every=0.01) is None


def test_a_free_port_is_a_port_nobody_listens_on():
    import socket
    ci = load("_ci")
    port = ci.free_port()
    assert 1024 < port < 65536
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


# ── tools/wheel_smoke.py ─────────────────────────────────────────────────────

def test_the_wheel_smoke_keeps_everything_in_its_own_folder(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("wheel_smoke", TOOLS / "wheel_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "uv_dir", lambda uv, *what: "/shared/" + "-".join(what))
    for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "GEMINI_CLI_HOME", "CURSOR_TRACE_ID"):
        monkeypatch.setenv(var, "/real/agent/config")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR", raising=False)
    work = tmp_path / "w"
    work.mkdir()
    env = smoke.clean_env("uv", work, 4242)
    for var in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
                "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "SHEAF_HOME"):
        assert Path(env[var]).is_relative_to(work), var
    assert env["SHEAF_PORT"] == "4242"
    assert env["PATH"].split(os.pathsep)[0] == str(work / "bin")
    assert not any(k.startswith(("CLAUDE", "CODEX", "GEMINI", "CURSOR")) for k in env)
    # its own runtime folder, not the real one and not the /tmp/sheaf-<uid> fallback
    run = Path(env["XDG_RUNTIME_DIR"])
    assert run.is_dir() and run.is_relative_to(work) and run.stat().st_mode & 0o777 == 0o700
    # uv's download cache and managed Pythons are shared, so nothing is fetched twice
    assert env["UV_CACHE_DIR"] == "/shared/cache" and env["UV_PYTHON_INSTALL_DIR"] == "/shared/python"


def test_the_wheel_smoke_says_what_it_cannot_isolate_on_macos(monkeypatch):
    """macOS ignores XDG_RUNTIME_DIR (paths.runtime_dir): there the smoke shares /tmp/sheaf-<uid>
    with the person's own sheaf, and its docstring and its output say so."""
    spec = importlib.util.spec_from_file_location("wheel_smoke", TOOLS / "wheel_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    assert smoke.runtime_note("linux") is None
    from sheafmd import paths
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert f"{paths.runtime_dir()}" in smoke.runtime_note("darwin"), "the note names what paths says"
    note = smoke.runtime_note("darwin")
    assert note and f"/tmp/sheaf-{os.getuid()}" in note and "shared" in note
    assert "macOS" in smoke.__doc__ and "/tmp/sheaf-" in smoke.__doc__


def test_the_wheel_smoke_strips_the_agent_variables_the_hub_client_strips(tmp_path, monkeypatch):
    # one list, read from hub/client.py, so the smoke cannot drift from it (OPENCODE was missing)
    from sheafmd.hub import client
    spec = importlib.util.spec_from_file_location("wheel_smoke", TOOLS / "wheel_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "uv_dir", lambda uv, *what: "/shared/" + "-".join(what))
    names = [p.rstrip("_") + "_SOMETHING" for p in client._AGENT_ENV_PREFIXES]
    for name in names:
        monkeypatch.setenv(name, "/real/agent/config")
    assert any(n.startswith("OPENCODE") for n in names)
    work = tmp_path / "w"
    work.mkdir()
    env = smoke.clean_env("uv", work, 4242)
    assert not [k for k in env if k.startswith(client._AGENT_ENV_PREFIXES)]
    assert not hasattr(smoke, "AGENT_PREFIXES")


def test_the_wheel_smoke_publishes_nothing():
    text = (TOOLS / "wheel_smoke.py").read_text(encoding="utf-8")
    for word in ("uv publish", "twine", "git tag", "pypi.org", "upload"):
        assert word not in text


def test_the_upgrade_command_is_a_newer_sheaf_meeting_the_hub_through_ensure_hub(monkeypatch):
    # `sheaf start` is not it: with the service installed it only asks the service to start, and
    # the version rule of SPEC 8.4 lives in ensure_hub.
    ci = load("_ci")
    seen = []
    monkeypatch.setattr(ci, "sh", lambda argv, **kw: seen.append(argv))
    ci.upgrade_command()
    (argv,) = seen
    code = argv[-1]
    compile(code, "<upgrade>", "exec")
    assert "__version__ = '99.0.0'" in code and "client.ensure_hub('cli'" in code
    assert code.index("__version__") < code.index("from sheafmd.hub import client")
    assert "'start'" not in code


def test_a_runner_that_is_a_container_with_no_systemd_skips_the_linux_service_checks_with_a_notice(bare, tmp_path):
    # A runner that is a container has no systemd, so there is no user service to
    # install. The script says so and ends well; it did not run `sheaf` or touch the home.
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "sheaf").write_text("#!/bin/sh\nexit 99\n")
    (fake / "sheaf").chmod(0o755)
    done = run("service_linux.py", {**bare, "PATH": str(fake), "GITHUB_ACTIONS": "true", "RUNNER_OS": "Linux"})
    assert done.returncode == 0, done.stdout + done.stderr
    assert "::notice::no systemd on this runner" in done.stdout
    assert "skipped" in done.stdout
    assert done.stderr == ""
    assert list(Path(bare["HOME"]).iterdir()) == []
    assert not Path(bare["SHEAF_HOME"]).exists()


# ── stall_watch.py ─────────────────────────────────────────────────

def stall(tmp_path, child_code, *, quiet="1", kill_after="4"):
    """tools/ci/stall_watch.py around a Python child, with a short quiet time."""
    child = tmp_path / "child.py"
    child.write_text(child_code)
    env = {**os.environ, "SHEAF_STALL_QUIET": quiet, "SHEAF_STALL_KILL_AFTER": kill_after}
    return subprocess.run([sys.executable, str(CI / "stall_watch.py"), "--", sys.executable, str(child)],
                          env=env, capture_output=True, text=True, timeout=60)


def test_stall_watch_passes_output_and_the_exit_code_of_a_command_that_does_not_stall(tmp_path):
    r = stall(tmp_path, "print('one'); print('two'); raise SystemExit(3)", quiet="30", kill_after="60")
    assert (r.returncode, r.stdout) == (3, "one\ntwo\n")


def test_stall_watch_names_where_a_silent_command_stood_and_ends_it(tmp_path):
    """The child registers faulthandler as tests/conftest.py does, then sits in a function; the
    watcher must print the process table and that function's name, and end the run with exit 1."""
    code = (
        "import faulthandler, os, signal, time\n"
        "from pathlib import Path\n"
        "Path(os.environ['SHEAF_PYTEST_PIDFILE']).write_text(str(os.getpid()))\n"
        "out = open(os.environ['SHEAF_STALL_DUMP'], 'a')\n"
        "faulthandler.register(signal.SIGUSR1, file=out, all_threads=True)\n"
        "faulthandler.register(signal.SIGUSR2, file=out, all_threads=False)\n"
        "def waiting_for_the_hub():\n"
        "    print('started', flush=True)\n"
        "    time.sleep(120)\n"
        "waiting_for_the_hub()\n")
    r = stall(tmp_path, code)
    assert r.returncode == 1
    assert "started" in r.stdout and "no output for" in r.stdout
    assert "waiting_for_the_hub" in r.stdout          # the stack of the stuck thread
    assert "PID" in r.stdout                          # the process table
    assert "ending the run" in r.stdout


def test_the_conftest_answers_sigusr1_with_the_stacks_of_a_real_pytest_run(tmp_path):
    """The hook of tests/conftest.py itself, not a fake child: a pytest run that sits in a test
    writes its pid where the watcher looks and dumps every thread on SIGUSR1."""
    import signal
    import time
    (tmp_path / "test_sits.py").write_text(f"import time\n\ndef test_sits_here():\n    open({str(tmp_path / 'in')!r}, 'w').close()\n    time.sleep(30)\n")
    pidfile, dump = tmp_path / "pid", tmp_path / "stacks"
    env = {**os.environ, "SHEAF_PYTEST_PIDFILE": str(pidfile), "SHEAF_STALL_DUMP": str(dump),
           "PYTHONPATH": os.pathsep.join([str(CI.parent.parent / "tests"), str(SRC)])}
    p = subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "conftest",
                          "--rootdir", str(tmp_path), str(tmp_path / "test_sits.py")],
                         env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=tmp_path)
    try:
        end = time.time() + 30
        while time.time() < end and not (pidfile.exists() and pidfile.read_text()):
            time.sleep(0.1)
        assert int(pidfile.read_text()) == p.pid
        end = time.time() + 30
        while time.time() < end and not (tmp_path / "in").exists():     # the test has started
            time.sleep(0.1)
        signals.send(p.pid, signal.SIGUSR1)
        end = time.time() + 10
        while time.time() < end and "test_sits_here" not in dump.read_text():
            time.sleep(0.1)
        assert "test_sits_here" in dump.read_text()
    finally:
        p.kill()
        p.wait()


@pytest.mark.skipif(sys.platform != "linux", reason="the watcher reads /proc and CI runs on Linux")
def test_stall_watch_shows_the_main_thread_of_a_real_pytest_run_that_has_more_than_a_hundred_threads(tmp_path):
    """faulthandler writes at most 100 threads, newest first: the main thread, the oldest, was the one
    left out of the stall dumps of two CI jobs. The watcher asks the main thread for its own."""
    (tmp_path / "test_sits.py").write_text(
        "import threading, time\n\n"
        "def test_sits_here():\n"
        "    stop = threading.Event()\n"
        "    for _ in range(120):\n"
        "        threading.Thread(target=stop.wait, daemon=True).start()\n"
        "    print('threads started', flush=True)\n"
        "    time.sleep(60)\n")
    env = {**os.environ, "SHEAF_STALL_QUIET": "2", "SHEAF_STALL_KILL_AFTER": "12",
           "PYTHONPATH": os.pathsep.join([str(CI.parent.parent / "tests"), str(SRC)])}
    r = subprocess.run([sys.executable, str(CI / "stall_watch.py"), "--", sys.executable, "-m", "pytest", "-s", "-q",
                        "-p", "no:cacheprovider", "-p", "conftest", "--rootdir", str(tmp_path), str(tmp_path / "test_sits.py")],
                       env=env, capture_output=True, text=True, timeout=90, cwd=tmp_path)
    out = r.stdout
    assert "threads started" in out and "no output for" in out
    assert out.count("Thread 0x") >= 100                         # the cap was reached, so the main thread is not in the second list
    main = out.split("main thread:")[1].split("all threads")[0]
    assert "test_sits_here" in main


def test_stall_watch_shows_the_name_of_a_test_whose_line_is_not_finished(tmp_path):
    """`pytest -v` prints `path::test ` and ends the line when the test ends: a stuck test is a line
    that never ends, and its name must reach the log."""
    r = stall(tmp_path, "import time\nprint('tests/x.py::test_the_stuck_one ', end='', flush=True)\ntime.sleep(60)\n")
    assert r.returncode == 1 and "tests/x.py::test_the_stuck_one " in r.stdout


def test_stall_watch_takes_its_child_down_when_the_job_is_cancelled(tmp_path):
    import signal
    import time
    marker = tmp_path / "child-pid"
    child = tmp_path / "child.py"
    child.write_text(f"import os, time\nopen({str(marker)!r}, 'w').write(str(os.getpid()))\ntime.sleep(60)\n")
    p = subprocess.Popen([sys.executable, str(CI / "stall_watch.py"), "--", sys.executable, str(child)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    end = time.time() + 20
    while time.time() < end and not (marker.exists() and marker.read_text()):
        time.sleep(0.1)
    pid = int(marker.read_text())
    p.send_signal(signal.SIGTERM)
    assert p.wait(30) == 128 + signal.SIGTERM
    end = time.time() + 5
    while time.time() < end:
        if proc_state(pid) != "alive":          # a zombie that no init reaps is as dead as a gone one
            return
        time.sleep(0.1)
    pytest.fail(f"the child {pid} is still running after the watcher was cancelled")
