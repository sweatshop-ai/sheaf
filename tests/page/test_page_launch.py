"""A browser that will not start fails a CI run with what is known about its death; on a person's machine it skips."""
import signal
import socket
import stat

import pytest

import pagehelp
from pagehelp import (close_context, died_report, how_it_ended, launched_binary, launch_chromium, new_context,
                      unavailable, until)

pytestmark = pytest.mark.page


class Died(Exception):
    pass


class FakeBrowserType:
    def __init__(self, exe="/nonexistent/chrome", error=None):
        self.executable_path, self.error = exe, error

    def launch(self):
        raise self.error or Died("BrowserType.launch: Target page, context or browser has been closed\nlog line")


def script(tmp_path, body):
    exe = tmp_path / "chrome"
    exe.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def dies_by(tmp_path, signum):
    return script(tmp_path, f"ulimit -c 0\necho 'dying words' >&2\nkill -{signum} $$")


def test_a_machine_that_is_not_ci_skips_a_browser_that_will_not_start():
    with pytest.raises(pytest.skip.Exception, match="Target page, context or browser has been closed"):
        launch_chromium(FakeBrowserType(), Died, in_ci=False)


def test_ci_fails_a_browser_that_will_not_start_with_the_whole_message_and_the_report(tmp_path):
    exe = dies_by(tmp_path, int(signal.SIGSEGV))
    with pytest.raises(pytest.fail.Exception) as e:
        launch_chromium(FakeBrowserType(str(exe)), Died, in_ci=True)
    msg = str(e.value)
    assert "log line" in msg                        # the lines after the first, where Playwright puts the browser's log
    assert "signal 11" in msg and "dying words" in msg


def test_the_report_gives_the_signal_that_ended_the_binary_and_what_it_wrote(tmp_path):
    assert "signal 6" in died_report(str(dies_by(tmp_path, int(signal.SIGABRT))))


def test_the_report_of_a_binary_that_is_not_there_says_so():
    assert "cannot be run" in died_report("/nonexistent/chrome")


def test_the_report_of_a_binary_that_exits_with_a_code_gives_the_code(tmp_path):
    assert "exit code 3" in died_report(str(script(tmp_path, "exit 3")))


def test_unavailable_skips_off_ci_and_fails_on_ci():
    with pytest.raises(pytest.skip.Exception, match="no package"):
        unavailable("no package", in_ci=False)
    with pytest.raises(pytest.fail.Exception, match="no package"):
        unavailable("no package", in_ci=True)


class FakeBrowser:
    def is_connected(self):
        return False

    def new_context(self, **kw):
        raise Died("Browser.new_context: Target page, context or browser has been closed")


def test_a_browser_that_died_under_a_new_context_fails_and_says_it_is_no_longer_connected():
    with pytest.raises(pytest.fail.Exception, match=r"(?s)connected=False.*Target page, context or browser"):
        new_context(FakeBrowser(), Died, viewport={"width": 1})


def test_the_report_runs_the_headless_shell_that_launch_runs_when_it_is_installed(tmp_path):
    chrome = tmp_path / "chromium-1/chrome-linux64/chrome"
    shell = tmp_path / "chromium_headless_shell-1/chrome-headless-shell-linux64/chrome-headless-shell"
    for f in (chrome, shell):
        f.parent.mkdir(parents=True)
        f.touch()
    assert launched_binary(str(chrome)) == str(shell)
    shell.unlink()
    assert launched_binary(str(chrome)) == str(chrome)


def test_the_headless_shell_is_the_one_of_the_same_revision_and_found_from_an_app_bundle(tmp_path):
    bundle = tmp_path / "chromium-2/chrome-mac/Chromium.app/Contents/MacOS/Chromium"
    old = tmp_path / "chromium_headless_shell-1/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    new = tmp_path / "chromium_headless_shell-2/chrome-headless-shell-mac-arm64/chrome-headless-shell"
    for f in (bundle, old, new):
        f.parent.mkdir(parents=True)
        f.touch()
    assert launched_binary(str(bundle)) == str(new)


def test_a_signal_with_no_name_is_still_reported():
    assert how_it_ended(-40) == "killed by signal 40"
    assert how_it_ended(-11) == "killed by signal 11 (SIGSEGV)"
    assert how_it_ended(0) == "exit code 0"


def test_a_shallow_path_has_no_headless_shell_beside_it():
    assert launched_binary("/chrome") == "/chrome"


def test_a_bug_of_the_test_under_a_new_context_is_not_called_a_dead_browser():
    class Bad(FakeBrowser):
        def new_context(self, **kw):
            raise TypeError("unexpected keyword")
    with pytest.raises(TypeError):
        new_context(Bad(), Died)


def test_a_second_run_that_hangs_is_reported_as_hung_with_what_it_wrote(tmp_path, monkeypatch):
    monkeypatch.setattr(pagehelp, "HANG_AFTER", 1)
    exe = script(tmp_path, "echo 'still starting' >&2\nexec sleep 30")
    report = died_report(str(exe))
    assert "still going after 1 s" in report and "still starting" in report


def test_the_headless_shell_of_linux_arm_has_another_name(tmp_path):
    chrome = tmp_path / "chromium-3/chrome-linux/chrome"
    shell = tmp_path / "chromium_headless_shell-3/chrome-linux/headless_shell"
    for f in (chrome, shell):
        f.parent.mkdir(parents=True)
        f.touch()
    assert launched_binary(str(chrome)) == str(shell)


def test_a_route_still_fetching_when_its_context_closes_does_not_fail_the_next_context(chromium):
    # CI, PR 13: a /_/doc route of one test was still in route.fetch at its teardown, and the next test's
    # new_context failed with "Route.fetch: Target page, context or browser has been closed".
    with socket.socket() as mute:
        mute.bind(("127.0.0.1", 0))
        mute.listen()
        url = f"http://127.0.0.1:{mute.getsockname()[1]}/"
        c = new_context(chromium)
        p = c.new_page()
        fetching = []

        def held(route):
            fetching.append(route.request.url)
            route.fetch()

        p.route(url + "slow", held)
        p.evaluate("u => { fetch(u).catch(() => {}); }", url + "slow")
        until(lambda: fetching, what="the route to be fetching")
        close_context(c)
    close_context(new_context(chromium))
