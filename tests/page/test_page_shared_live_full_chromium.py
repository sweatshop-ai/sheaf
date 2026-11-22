"""The shared stream (page/live.js) in the full Chromium, not the headless shell the other page tests run on
(ticket 180). In the full Chromium a follower's join reached the leader over the BroadcastChannel before the
follower's own `sheaf-tab-<TAB>` lock request reached the lock manager. The leader's watch on that lock was granted at
once, found the lock neither held nor pending, and dropped the tab: the hub counted one tab of three, and no follower
heard a change until it was reloaded. The headless shell orders the two the other way, so the tests there passed."""
import pytest

from pagehelp import DOC, RELOADING, close_context, launch_engine, new_context, rewrite, until

pytestmark = pytest.mark.page


@pytest.fixture(scope="module")
def full_chromium(chromium):
    # From the session's driver (chromium.pw): `until` pumps that driver's events, so these pages' events come too.
    b = launch_engine(chromium.pw.chromium, "chromium", channel="chromium")
    yield b
    b.close()


@pytest.fixture
def shared(full_chromium, site):
    c = new_context(full_chromium, shared=True, viewport={"width": 1100, "height": 800})
    c.add_cookies([site.cookie()])
    yield c
    close_context(c)


def opened(context, site):
    p = context.new_page()
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(site.url)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    return p, errors


def shows(p, text):
    try:
        return text in p.evaluate("document.body.textContent")
    except Exception as e:
        if any(said in str(e) for said in RELOADING):
            return False
        raise


def test_full_chromium_counts_every_tab_and_a_follower_hears_a_change(shared, site):
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted by the hub")
    # A dropped follower is dropped a few milliseconds after its join: it must still be counted a sweep later.
    pages[0][0].wait_for_timeout(2500)
    assert site.hub.tabs(DOC) == 3, f"{site.hub.tabs(DOC)} tabs counted after 2.5 s, not 3"
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nHeard by a follower.\n")
    for n, (p, _) in enumerate(pages[1:], 2):     # the first tab took the lock: the others follow
        until(lambda: shows(p, "Heard by a follower."), what=f"the change in follower tab {n}")
    assert [e for _, e in pages] == [[]] * 3
