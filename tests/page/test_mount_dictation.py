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
