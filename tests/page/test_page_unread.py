"""The page's unread badge (SPEC 8.7, 10.4) reads the last author as the hub names it (5.3), as the index and the
door's `documents` do: a legacy `"Claude (action)"` reply is Claude's, so for a person named Claude it is their own."""
import pytest
from helpers import thread, with_threads

pytestmark = pytest.mark.page


def badge(tab, cid):
    return tab.page.locator(f'.rd-anchor[data-rd-id="{cid}"]')


def test_a_legacy_action_reply_is_read_for_a_person_named_claude(tab):
    site = tab.site
    site.hub.person = "Claude"
    site.file.write_text(with_threads(thread("c1", "Bob", "Claude (action)"), thread("c2", "Bob")), encoding="utf-8")
    tab.open()
    badge(tab, "c2").wait_for(state="attached")
    assert "rd-unread" in badge(tab, "c2").get_attribute("class")         # Bob's own thread: unread, so the page drew it
    assert "rd-unread" not in badge(tab, "c1").get_attribute("class")
