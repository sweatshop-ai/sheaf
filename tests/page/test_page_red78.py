"""The comment form on a phone with its keyboard up (SPEC 10.4).

iOS does not shrink the layout viewport for its keyboard: `innerHeight` stays, and `visualViewport` shrinks (and
scrolls) instead. Chromium has no keyboard, so a `visualViewport` that the test controls stands in for it.
What this cannot prove: iOS's own keyboard, its suggestion bar, the AutoFill pill and the dismiss button (they
are drawn by the system; the test leaves ACCESSORY px for them), and whether iOS zooms and pans on focus (the
test shows the cause the page controls: a 14px font, and a page wider than the screen). Only a real iPhone shows it."""
import pytest

from pagehelp import at, select, select_by_touch

pytestmark = pytest.mark.page

MD = "# Plan\n\nSecond paragraph, about pears.\n"
MAIN = "main"
POP = "#rd-popover"
ACCESSORY = 48          # px the form must keep clear above the keyboard, for the suggestion bar and the AutoFill pill (the page keeps 56)
KEYBOARD = 336          # px of keyboard on a 390x844 iPhone

# A visualViewport that the test moves, as iOS does when the keyboard opens (it shrinks, and scrolls to the focus).
FAKE_VV = """(() => {
  const t = new EventTarget();
  const vv = { width: 390, height: 844, offsetLeft: 0, offsetTop: 0, scale: 1, pageLeft: 0, pageTop: 0,
    addEventListener: (...a) => t.addEventListener(...a), removeEventListener: (...a) => t.removeEventListener(...a) };
  Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
  window.__keyboard = (height, top) => { vv.height = height; vv.offsetTop = top || 0; t.dispatchEvent(new Event('resize')); };
})()"""


@pytest.fixture
def phone(touch_tab, site):
    site.file.write_text(MD, encoding="utf-8")
    touch_tab.page.add_init_script(FAKE_VV)
    return touch_tab.open()


def keyboard(page, height, top=0):
    page.evaluate("([h, t]) => window.__keyboard(h, t)", [height, top])
    page.wait_for_timeout(300)


def rects(page):
    """The popover, its buttons and its text field, as [left, top, right, bottom] in viewport px."""
    return page.evaluate("""() => { const r = (e) => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };
        const p = document.querySelector('#rd-popover'), t = p.querySelector('textarea');
        return { pop: r(p), buttons: [...p.querySelectorAll('.rd-form button')].map(r), field: r(t) }; }""")


@pytest.mark.parametrize('n', range(60))
def test_repeat_old(phone, n):
    """The thread gives way to the form, down to its floor: with a long comment and the keyboard up, the field and
    its buttons are still inside the docked popover and above the keyboard."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    update_file(phone.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph",
                                                           "Nearly good, only a pity about my name. " * 20, "Ada", "2026-10-25T21:01")[0])
    page = phone.open().page
    page.click(".rd-badge")
    page.wait_for_selector(POP + " textarea")
    page.focus(POP + " textarea")
    keyboard(page, 450)
    got = rects(page)
    assert got["pop"][3] <= 450 - ACCESSORY, got
    assert got["field"][1] >= got["pop"][1] and got["field"][3] <= got["pop"][3], got
    assert all(b[3] <= got["pop"][3] for b in got["buttons"]), got


def test_mechanism(phone):
    """The open page reloads itself when its file changes; a goto during that reload is the ticket's error."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    page = phone.page
    loads = []
    page.on("request", lambda r: loads.append(r.url) if r.resource_type == "document" else None)
    def slow(route):
        page.wait_for_timeout(1500)
        route.continue_()
    page.route("**/work/plan.md", slow)
    update_file(phone.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph",
                                                           "Nearly good. " * 20, "Ada", "2026-10-25T21:01")[0])
    deadline = 0
    while not loads and deadline < 100:
        page.wait_for_timeout(100); deadline += 1
    print("SELFRELOAD documents requested by the page itself:", len(loads))
    assert loads, "the page did not reload itself within 10 s"
    page.goto(phone.site.url)
