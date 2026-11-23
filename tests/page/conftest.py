"""The page in a real browser (SPEC 18, "Page (Playwright)").

A hub runs on a thread of this process, on a port of its own and under the test's temporary home
(the autouse `sheaf_env` and `port` fixtures of tests/conftest.py), never on 27419. Chromium is
Playwright's; a run without it, or without the package, skips these tests with the reason, except in CI
(the `CI` variable, which GitHub sets to true), where it fails.
Every test here carries the `page` mark, so `-m "not page"` leaves them out.
"""
import inspect
import os
import re
import socket
import time

import pytest

import driver_stall
import stall_evidence
from agent_fakes import PID, FakeClaude, Peer, write_record
from helpers import PLAN
from pagehelp import (DOC, PageStalled, close_context, landed, launch_chromium, new_context, note_route, settle_routes,
                      stalls_after, unavailable, use_pump)
from sheafmd import paths
from sheafmd.agents.base import Target
from sheafmd.agents.claude_code import proc_start
from sheafmd.hub import events, handler, server
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
        extra = stall_evidence.launch_args()
        b = launch_chromium(pw.chromium, sync_api.Error, in_ci, **({"args": extra} if extra else {}))
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
    """A Claude Code session the hub can Tell, as the page's document is rendered from it.
    Nothing real is reached: the session is a record in the test's own folder, its socket a thread
    of the test, and `claude` (the value of this fixture) a script that writes down each call. Open the page after this fixture has run."""
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
    try:
        landed(t.page)
    finally:        # a reload that does not land does not hide the script errors the page raised
        assert t.errors == [], "the page raised script errors"


# ── the journal of the event stream (ticket 100) ───────────────────────────────────────────────────────────
# A hub event that does not reach the page was seen only on a loaded CI runner, never by hand. A failing test
# says what the stream did: the page's side (`STREAM_JOURNAL_JS` of pagehelp: opens, errors, each event, in real
# time) and the hub's (each publish, each frame written to a stream), side by side, so a lost event shows as one
# side without the other.
PROBE = "x-route-probe"
PROBED = ("**/_/comment",)      # the routes that are probed (and any regex that matches the probe's URL): a probe is a request, which a test's own `request` listener sees too,
                                # and no test listens for /_/comment (the others do: _/pin, _/save, _/tell, _/tick, _/cancel)
PROBE_PATH = "/_/comment"


def probed(pattern, origin):
    """Whether a route of this pattern is probed: the glob of PROBED, or a regex that the probe's own URL matches."""
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(origin + PROBE_PATH))
    return isinstance(pattern, str) and pattern in PROBED


def until_live(page, pattern, log):
    """`route()` returns when Playwright has told the browser to intercept, yet on a loaded runner a request the page sent a few
    ms later (a send after Ctrl+Enter) went straight to the hub and the test's handler never saw it (ticket 100: three tests
    timed out "waiting for the send to go out", the hub's /_/comment in 2 ms after the page's fetch, no handler call). So the
    route counts as live once it has caught a request of its own: a GET with a probe header that the wrapper's handler answers
    itself, with 204. Best effort. Limits: only the PROBED routes (the glob, and any regex that matches the probe's URL), whatever their handler;
    a route of a context is probed through its first page, which says nothing of a send from another page; the wrapper answers a
    probe for any route that matches it, so an earlier live broad route (`**/*`) answers the probe of a newer one at try 1, which proves nothing about the newer one; a regex tied to the hub's origin is not probed on a page of another origin; a page that is
    reloading is left."""
    if page is None or not page.url.startswith("http"):
        return
    origin = "/".join(page.url.split("/")[:3])
    if not probed(pattern, origin):
        return
    name = pattern.pattern if isinstance(pattern, re.Pattern) else pattern
    probe = f"fetch({origin + PROBE_PATH!r}, {{headers: {{{PROBE!r}: '1'}}}}).then(r => r.status, () => 0)"
    began = time.monotonic()
    tries = 0
    while time.monotonic() - began < 5:
        tries += 1
        try:
            with stalls_after(8, "a route's probe"):
                caught = page.evaluate(probe) == 204
        except (Exception, PageStalled) as e:
            log.append((time.time(), f"route {name} not probed: {str(e).splitlines()[0][:100]}"))
            return
        if caught:
            log.append((time.time(), f"route {name} live: caught its probe at try {tries}"))
            return
        page.wait_for_timeout(50)
    log.append((time.time(), f"route {name} did NOT catch its probe in {tries} tries over 5 s"))


@pytest.fixture(autouse=True)
def hub_journal(monkeypatch):
    """What the hub published and wrote to a stream, with the time (time.time()), for `pytest_runtest_makereport`.
    It also notes every route a handler of the test is given, so that one the test kept and never answered is
    answered when its context closes, or here at the end of the test (pagehelp.settle_routes)."""
    log = []
    publish, frame = events.Bus.publish, server.frame

    def noting_publish(self, name, data):
        log.append((time.time(), f"publish {name} to {self.count()} stream(s) {str(data)[:100]}"))
        return publish(self, name, data)

    def noting_frame(name, data):
        log.append((time.time(), f"write {name}"))
        return frame(name, data)
    comment = handler.Handler._comment

    def noting_comment(self, req):
        log.append((time.time(), f"/_/comment in: op {req.body.get('op')} rid {req.body.get('rid')}"))
        try:
            return comment(self, req)
        finally:
            log.append((time.time(), f"/_/comment out: rid {req.body.get('rid')}"))
    monkeypatch.setattr(handler.Handler, "_comment", noting_comment)
    try:
        from playwright.sync_api import BrowserContext, Page
    except ImportError:
        Page = BrowserContext = None
    for cls in (Page, BrowserContext):
        if cls is None:
            continue

        wrappers = {}       # (the object routed, url, id of the test's handler) -> the handlers Playwright holds, for `unroute(url, handler)`

        def noting_route(self, url, handler, *a, _route=cls.route, _name=cls.__name__, _wrappers=wrappers, **kw):
            def noted(route):
                log.append((time.time(), f"{_name}.route handler called for {route.request.method} {route.request.url[-30:]}"))

            def run(route, *args):
                if route.request.headers.get(PROBE):
                    return route.fulfill(status=204)
                noted(route)
                note_route(self if _name == "BrowserContext" else self.context, route)
                return handler(*args)
            # Playwright passes the request too to a handler that takes two arguments, and none to one that takes none.
            n = len(inspect.signature(handler).parameters)
            if n == 0:
                def called():
                    return handler()
            elif n == 1:
                def called(route):
                    return run(route, route)
            else:
                def called(route, request):
                    return run(route, route, request)
            _wrappers.setdefault((id(self), url, id(handler)), []).append(called)     # id: a handler need not be hashable
            log.append((time.time(), f"{_name}.route({url}) asked"))
            out = _route(self, url, called, *a, **kw)
            log.append((time.time(), f"{_name}.route({url}) registered"))
            if isinstance(url, (str, re.Pattern)) and n > 0 and "times" not in kw and not a:     # `times=` counts the probe as a use
                until_live(self if _name == "Page" else (self.pages[0] if self.pages else None), url, log)
            return out

        def unrouting(self, url, handler=None, *, _unroute=cls.unroute, _wrappers=wrappers):
            if handler is None:
                for key in [k for k in _wrappers if k[:2] == (id(self), url)]:
                    del _wrappers[key]
                return _unroute(self, url)
            held = _wrappers.pop((id(self), url, id(handler)), None)
            if held is None:
                return _unroute(self, url, handler)
            for called in held:          # Playwright takes off every route of the pair; each registration here has a handler of its own
                out = _unroute(self, url, called)
            return out
        monkeypatch.setattr(cls, "unroute", unrouting)
        monkeypatch.setattr(cls, "route", noting_route)
    monkeypatch.setattr(events.Bus, "publish", noting_publish)
    monkeypatch.setattr(server, "frame", noting_frame)
    yield log
    settle_routes()


def stream_journal(pages, hub):
    """The two journals as one text, oldest first, each line a time of day and the side it comes from."""
    lines = [(t, "hub  ", what) for t, what in hub]
    for i, page in enumerate(pages):
        try:
            with stalls_after(5, "the page's journal"):
                got = page.evaluate("window.__sseJournal || []")
        except (Exception, PageStalled) as e:
            lines.append((time.time(), f"page{i}", f"journal unreadable: {str(e)[:80]}"))
            continue
        lines += [(t / 1000, f"page{i}", f"{what} {data}") for t, what, data in got]
    return "\n".join(f"{time.strftime('%H:%M:%S', time.localtime(t))}.{int(t * 1000) % 1000:03d} {side} {what}"
                     for t, side, what in sorted(lines))


def stalled(call, rep):
    """Why a failed phase counts as a stall whose evidence is kept, or None: the page stopped answering (PageStalled),
    or pytest-timeout ended the phase (inside the driver or not: tests/driver_stall.py ends the run on the first)."""
    if not rep.failed:
        return None
    if call.excinfo is not None and call.excinfo.errisinstance(PageStalled):
        return f"PageStalled: {call.excinfo.value}"
    text = str(rep.longrepr or "")
    if driver_stall.TIMED_OUT in text:
        inside = driver_stall.stalled_in_driver(rep) is not None
        return "pytest-timeout" + (", inside the Playwright driver" if inside else "") + "\n\n" + text[-6000:]
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    out = yield
    rep = out.get_result()
    why = stalled(call, rep)
    if why is not None:
        # First, and through no Playwright call: the journal below asks the driver, which may be the part that froze.
        kept = stall_evidence.save(item.nodeid, rep.when, why, item.funcargs.get("hub_journal"))
        if kept is not None:
            rep.sections.append(("stall evidence", f"kept in {kept}"))
    if rep.when != "call" or not rep.failed:
        return
    ctx = item.funcargs.get("context")
    if ctx is None and "touch_tab" in item.funcargs:
        ctx = item.funcargs["touch_tab"].page.context
    if ctx is not None and "hub_journal" in item.fixturenames:
        rep.sections.append(("the event stream, page and hub", stream_journal(ctx.pages, item.funcargs["hub_journal"])))
