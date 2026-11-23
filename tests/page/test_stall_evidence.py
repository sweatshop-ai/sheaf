"""The evidence of a stalled page test is kept even when the Playwright driver itself has frozen (ticket 173 O)."""
import signal
import threading

import pytest

import stall_evidence
from sheafmd import signals
from pagehelp import close_context, launch_chromium, new_context, until

pytestmark = pytest.mark.page


def driver_pid(browser):
    """The pid of the Playwright driver (node) behind the session's browser. It walks Playwright's private attributes
    (1.58): a Playwright that moves them fails this test here, not in silence."""
    return browser.pw._impl_obj._connection._transport._proc.pid


def journal_of(page):
    return [what for _, what, _ in page.evaluate("window.__sseJournal || []")]


def test_with_the_driver_frozen_the_evidence_holds_the_pages_journal_the_hubs_and_the_stacks(chromium, site, hub_journal,
                                                                                              tmp_path):
    from playwright.sync_api import Error
    port = stall_evidence.free_port()
    browser = launch_chromium(chromium.pw.chromium, Error, True, args=[f"--remote-debugging-port={port}"])
    context = None
    try:
        context = new_context(browser)
        context.add_cookies([site.cookie()])
        page = context.new_page()
        page.goto(site.url)
        until(lambda: "event hello" in journal_of(page), what="the page's first hello")
        driver = driver_pid(chromium)
        # A stopped driver answers nothing, as the one of the macOS run did. Whatever happens below, it goes on.
        resume = threading.Timer(60, lambda: signals.send(driver, signal.SIGCONT))
        resume.start()
        signals.send(driver, signal.SIGSTOP)
        try:
            kept = stall_evidence.save("tests/page/x.py::stalled", "call", "a stall made by the test", hub_journal,
                                       port=port, into=tmp_path)
        finally:
            signals.send(driver, signal.SIGCONT)
            resume.cancel()
        pages = (kept / "pages.txt").read_text()
        assert site.url in pages, pages
        assert "event hello" in pages and '"version"' in pages, pages
        assert "leaving=False sameLoad=False" in pages, pages
        assert "write hello" in (kept / "hub-journal.txt").read_text()
        assert test_with_the_driver_frozen_the_evidence_holds_the_pages_journal_the_hubs_and_the_stacks.__name__ in \
            (kept / "stacks.txt").read_text()
        assert str(driver) in (kept / "processes.txt").read_text()
        assert "a stall made by the test" in (kept / "why.txt").read_text()
    finally:
        if context is not None:
            close_context(context)
        browser.close()


def test_a_browser_that_does_not_answer_is_said_and_the_rest_is_kept(tmp_path):
    port = stall_evidence.free_port()          # nothing listens there
    kept = stall_evidence.save("tests/page/x.py::stalled", "setup", "why", [(0.0, "publish hello")], port=port, into=tmp_path)
    assert "the browser process did not list its targets" in (kept / "pages.txt").read_text()
    assert "publish hello" in (kept / "hub-journal.txt").read_text()
    assert (kept / "stacks.txt").read_text().startswith("--- thread")


def test_with_no_folder_named_nothing_is_kept_and_chromium_opens_no_port(monkeypatch):
    monkeypatch.delenv(stall_evidence.ENV, raising=False)
    assert stall_evidence.launch_args() == []
    assert stall_evidence.save("tests/page/x.py::stalled", "call", "why") is None
