"""The microphone of the chat box on a page mounted in the front (ticket 06, SPEC 10.4): the sound goes to the host's own
Open WebUI route with the session cookie, and to nothing else; and a hub page in proxy mode that is not mounted has no
microphone (SPEC 9.9). Fakes as in test_page_dictation.py: no real microphone, no real service."""
import pytest

from pagehelp import until
from sheafmd import comments as rdc
from sheafmd.source import update_file
from test_mount_page import front  # noqa: F401 - the fixture
from test_page_dictation import FAKE_MIC
from test_page_proxy import as_member  # noqa: F401 - the fixture

pytestmark = pytest.mark.page

ROUTE = "**/api/v1/audio/transcriptions"
MIC = ".rd-mic"
FIELD = "#rd-popover textarea"


def test_a_mounted_page_sends_the_sound_to_the_hosts_route_with_the_cookie_and_no_token(front, site):  # noqa: F811
    seen = []

    def answer(route):
        seen.append({"url": route.request.url, "headers": route.request.headers, "body": route.request.post_data_buffer})
        route.fulfill(status=200, content_type="application/json", body='{"text":"from the host"}')
    front.page.route(ROUTE, answer)
    front.page.add_init_script(FAKE_MIC + """(() => { window.__reads = []; window.__creds = [];
      const send = window.fetch; window.fetch = function (u, i) { window.__creds.push([String(u), i && i.credentials]); return send.apply(this, arguments); };
      const get = Storage.prototype.getItem; Storage.prototype.getItem = function (k) { window.__reads.push(k); return get.call(this, k); }; })();""")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    front.open()
    front.click(".rd-badge")
    front.click(MIC)
    until(lambda: front.page.evaluate("window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'"), what="recording")
    front.click(MIC)
    until(lambda: seen, what="the sound sent to the host")
    until(lambda: front.js("return root.querySelector(arg).value", FIELD) == "from the host", what="the text in the field")
    req = seen[0]
    assert req["url"] == site.base + "/api/v1/audio/transcriptions"
    assert "authorization" not in req["headers"], "the page made a token of its own"
    assert req["headers"]["content-type"].startswith("multipart/form-data")
    assert b'filename="dictee.webm"' in req["body"]
    assert "token" not in front.page.evaluate("window.__reads"), "the page read a stored token"
    assert [c[1] for c in front.page.evaluate("window.__creds") if c[0].endswith("/api/v1/audio/transcriptions")] == [
        "same-origin"], "the session cookie does not go with the sound"


def test_a_hub_page_in_proxy_mode_that_is_not_mounted_has_no_microphone(tab, site, as_member):  # noqa: F811
    asked = []
    tab.page.context.add_init_script(FAKE_MIC)
    tab.page.context.route("**/_/transcribe", lambda route: (asked.append(route.request.method), route.fulfill(
        status=200, content_type="application/json", body='{"available":true}')))
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    tab.page.wait_for_timeout(300)
    assert tab.page.locator("#rd-popover " + MIC).count() == 0
    assert asked == [], "the page asked a relay that does not exist in proxy mode"


def _refuse_and_remount(front, site, status, between=lambda: None):
    front.page.route(ROUTE, lambda route: route.fulfill(status=status, content_type="application/json", body="{}"))
    front.page.add_init_script(FAKE_MIC)
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    front.open()
    front.click(".rd-badge")
    front.click(MIC)
    until(lambda: front.page.evaluate("window.__mic.made.length === 1 && window.__mic.made[0].state === 'recording'"), what="recording")
    front.click(MIC)
    until(lambda: not front.has(MIC), what="the button gone after the refusal")
    between()
    front.js("root.querySelector('main').__old = 1;")
    front.page.evaluate("window.__page.remount()")
    until(lambda: front.js("return root.querySelector('main') && root.querySelector('main').__old === undefined;")
          and front.has(".rd-badge"), what="the remounted page")
    for _ in range(30):           # the remount keeps the thread open, so a click on the badge would close it
        if front.has(FIELD):
            break
        front.page.wait_for_timeout(100)
    else:
        front.click(".rd-badge")
    until(lambda: front.has(FIELD), what="the form of the thread")     # the closed root: page selectors do not reach it
    front.page.wait_for_timeout(300)


def test_a_refusal_of_the_account_stays_off_after_a_remount(front, site):  # noqa: F811
    """SPEC 10.4: a 403 takes the button away 'for the session', not for the mount."""
    _refuse_and_remount(front, site, 403)
    assert not front.has(MIC), "the remount brought the button back"


def test_a_lost_service_is_held_off_for_the_mount_only(front, site):  # noqa: F811
    """A 404, a 401 or a network failure may be a moment, an expired login or a host without the route: a sign-in
    must not leave it off for the tab (the ticket-44 review), so the next mount offers the button again."""
    _refuse_and_remount(front, site, 404)
    until(lambda: front.has(MIC), what="the button offered again by the next mount")


def _as_member(front, who):
    """The hub's answer for the mount names the member `who[0]`: a change of who[0] is a change of user."""
    def answer(route):
        got = route.fetch()
        body = got.json()
        body["config"]["proxy"], body["config"]["member"] = True, who[0]
        route.fulfill(response=got, json=body)
    front.page.route("**/_/mount?doc=*", answer)


def test_a_refusal_does_not_follow_a_change_of_user_in_the_same_tab(front, site):  # noqa: F811
    who = ["bea"]
    _as_member(front, who)
    _refuse_and_remount(front, site, 403, between=lambda: who.__setitem__(0, "carl"))
    until(lambda: front.has(MIC), what="the button offered to the next user")


def test_a_refusal_stays_with_the_same_user_after_a_remount(front, site):  # noqa: F811
    _as_member(front, ["bea"])
    _refuse_and_remount(front, site, 403)
    assert not front.has(MIC), "the remount brought the button back for the same user"


def test_a_session_storage_that_throws_does_not_break_the_dictation(front, site):  # noqa: F811
    front.page.add_init_script("""(() => { const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function (k) { if (String(k).includes('rd-dict-off')) throw new DOMException('no', 'SecurityError');
        return set.apply(this, arguments); };
      const get = Storage.prototype.getItem;
      Storage.prototype.getItem = function (k) { if (String(k).includes('rd-dict-off')) throw new DOMException('no', 'SecurityError');
        return get.apply(this, arguments); }; })();""")
    _refuse_and_remount(front, site, 403)
    # Nothing could be kept, so the state is the mount's: the page works and the button is offered again.
    until(lambda: front.has(MIC), what="the button offered again by a mount that kept nothing")
