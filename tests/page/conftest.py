"""The page in a real browser (SPEC 18, "Page (Playwright)").

A hub runs on a thread of this process, on a port of its own and under the test's temporary home
(the autouse `sheaf_env` and `port` fixtures of tests/conftest.py), never on 27419. Chromium is
Playwright's; a run without it, or without the package, skips these tests with the reason, except in CI
(the `CI` variable, which GitHub sets to true), where it fails.
Every test here carries the `page` mark, so `-m "not page"` leaves them out.
"""
import os
import socket

import pytest

from agent_fakes import PID, FakeClaude, Peer, write_record
from helpers import PLAN
from pagehelp import DOC, close_context, launch_chromium, new_context, unavailable, use_pump
from sheafmd import paths
from sheafmd.agents.base import Target
from sheafmd.agents.claude_code import proc_start
from sheafmd.hub import server
from sheafmd.hub.core import Hub


class Site:
    """The hub of one test, and the means to take it away and bring it back."""

    def __init__(self, port, doc_file):
        self.port, self.file = port, doc_file
        self.hub = self.srv = None
        self.start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def url(self):
        return f"{self.base}/{DOC}"

    def start(self, *, key=None, **hub):
        """A hub on this site's port: a new boot, the same key, the same files. `key` and the
        rest (`version`, `service`) are what a hub that came back different looks like."""
        self.hub = Hub(port=self.port, key=key or paths.ensure_key(), started_by="test", **hub)
        self._serve()
        self.hub.roots.for_document(self.file)

    def reopen(self):
        """The same hub, with the same boot, answering again after a `kill()`: a blip of the network."""
        self._serve()

    def _serve(self):
        sock = server.bind(self.port)
        self.srv = server.HubServer(self.hub, sock)
        # Remember every connection, so that a hub taken away takes its open ones with it: a
        # closed server alone leaves a keep-alive connection answering, which no outage does.
        self.conns = conns = []
        accept = self.srv.httpd.get_request

        def get_request():
            c, a = accept()
            conns.append(c)
            return c, a
        self.srv.httpd.get_request = get_request
        self.srv.start()

    def stop(self, reason="stop"):
        """A clean stop: the streams are told, then the hub goes."""
        self.srv.stop(reason)
        self.srv.close()
        self._drop()

    def kill(self):
        """The hub gone without a word, as a crash or a closed laptop lid looks from the page."""
        self.srv.close()
        self._drop()

    def _drop(self):
        for c in self.conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def cookie(self):
        return {"name": self.hub.auth.cookie_name, "value": self.hub.auth.cookie_value(),
                "url": self.base}


@pytest.fixture(scope="session")
def chromium():
    in_ci = os.environ.get("CI", "").lower() in ("1", "true")
    try:
        from playwright import sync_api
    except ImportError:
        unavailable("the playwright package is not installed", in_ci)
    pw = sync_api.sync_playwright().start()
    try:
        b = launch_chromium(pw.chromium, sync_api.Error, in_ci)
    except BaseException:
        pw.stop()
        raise
    b.pw = pw               # the one driver of this thread: another engine is launched from it (test_mount_page.py)
    # A page of its own for the waits: a call on it delivers the events of every page (pagehelp.until).
    idle = new_context(b).new_page()
    was = use_pump(lambda seconds: idle.wait_for_timeout(seconds * 1000))
    yield b
    use_pump(was)
    b.close()
    pw.stop()


@pytest.fixture
def site(work, port):
    f = work / "plan.md"
    f.write_text(PLAN, encoding="utf-8")
    s = Site(port, f)
    yield s
    s.srv.close()


@pytest.fixture
def agent(site, tmp_path, short_tmp):
    """A Claude Code session the hub can Ask and Tell, as the page's document is rendered from it.
    Nothing real is reached: the session is a record in the test's own folder, its socket a thread
    of the test, and `claude` (the value of this fixture) a script that answers "The answer." and
    writes down each call. Open the page after this fixture has run."""
    cfg = tmp_path / "claude-config"
    peer = Peer(os.path.join(short_tmp, "s.sock"))
    claude = FakeClaude(tmp_path / "fake")
    write_record(cfg, messagingSocketPath=peer.path)
    target = Target.from_dict({"agent": "claude-code", "session": "s-1", "pid": PID, "socket": peer.path,
                               "name": "Cosima", "cwd": str(site.file.parent), "bin": str(claude.bin),
                               "config_dir": str(cfg), "proc_start": proc_start(PID)}).as_dict()
    site.hub.render(site.file, {}, target)
    yield claude
    site.hub.runner.kill_all()
    site.hub.runner.join(10)
    peer.close()


class Tab:
    """A signed-in page of the site. `errors` holds every script error the page raised."""

    def __init__(self, page, site):
        self.page, self.site, self.errors = page, site, []
        page.on("pageerror", lambda e: self.errors.append(str(e)))

    def open(self):
        self.page.goto(self.site.url)
        self.page.wait_for_selector("#rd-menu-btn", state="attached")
        return self


@pytest.fixture
def context(chromium, site):
    c = new_context(chromium, viewport={"width": 1100, "height": 800})
    c.add_cookies([site.cookie()])
    yield c
    close_context(c)


@pytest.fixture
def touch_tab(chromium, site):
    """A phone: 390x844, touch, mobile. A selection made here fires `selectionchange` and no mouse event."""
    c = new_context(chromium, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True,
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148")
    c.add_cookies([site.cookie()])
    t = Tab(c.new_page(), site)
    yield t
    try:
        assert t.errors == [], "the page raised script errors"
    finally:
        close_context(c)


@pytest.fixture
def tab(context, site):
    t = Tab(context.new_page(), site)
    yield t
    assert t.errors == [], "the page raised script errors"
