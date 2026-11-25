"""A member's page opened on its own address (no mount bundle, only the page script) links the byline's session name to the chat
(SPEC 6.2 item 11). Browser test: it runs in CI, never on the laptop; a browser that cannot start is skipped off CI and fails in CI."""
import json

import pytest

from pagehelp import launch_engine
from sheafmd.render import page_script

pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.page
ORIGIN = "http://sheaf.test"


def test_the_byline_of_a_directly_opened_page_links_to_the_chat(chromium):
    cfg = {"doc": "a.md", "proxy": True, "can": [], "way_back": {"name": "Cosima", "tip": "the session", "link": {"kind": "chat", "href": "/chat/42"}}}
    html = ("<!doctype html><title>t</title><body><main><h1>T</h1><p class=\"doc-by\" data-rd-ui>Document prepared by someone</p></main>"
            f"<script type=\"application/json\" id=\"rd-edit-meta\">{json.dumps(cfg)}</script><script>{page_script()}</script></body>")
    browser = launch_engine(chromium.pw.chromium, "chromium")
    try:
        page = browser.new_context().new_page()
        page.route("**/*", lambda r: r.fulfill(content_type="text/html", body=html) if r.request.url == ORIGIN + "/"
                   else r.fulfill(status=200, content_type="application/json", body="{}"))
        page.goto(ORIGIN + "/")
        link = page.locator("p.doc-by a")
        link.wait_for(timeout=20_000)
        assert link.inner_text() == "Cosima" and link.get_attribute("href") == "/chat/42"
    finally:
        browser.close()
