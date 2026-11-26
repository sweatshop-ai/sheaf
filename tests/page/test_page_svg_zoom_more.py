"""The diagram viewer (SPEC 6.9), second round: a pinch keeps what is between the fingers between them, the legend of a
chart stays in the viewer, a link inside an SVG is the link's own whichever way it is written, and the keyboard opens it."""
import pytest

from pagehelp import until, rewrite

pytestmark = pytest.mark.page

VIEWER = "#rd-zoom"
STAGE = "#rd-zoom .rd-zoom-stage"
BANDED = ('```chart\n{"type": "bar", "x": ["north", "south"], "series": [{"name": "Sales", "values": [10, 20]}],\n'
          ' "bands": [{"from": 0, "to": 15, "color": "green", "label": "on target"}]}\n```\n')
PIC = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">'
       '<rect width="200" height="100" fill="#fde68a"/></svg>')
LINKED = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 200 100" '
          'width="200" height="100"><a xlink:href="#elsewhere"><rect id="hot" width="200" height="100" fill="#fde68a"/></a></svg>')
MD = f'# Plan\n\n{BANDED}\n![A round thing](pic.svg)\n\n<div class="mermaid-svg">{LINKED}</div>\n\nAfter.\n'
PTR = """([type, id, x, y]) => document.querySelector('#rd-zoom').dispatchEvent(new PointerEvent(type,
  {pointerId: id, pointerType: 'touch', clientX: x, clientY: y, bubbles: true, isPrimary: id === 1}))"""


@pytest.fixture
def doc(tab, site):
    (site.file.parent / "pic.svg").write_text(PIC)
    rewrite(site.file, MD)
    return tab.open()


def box(p, css):
    return p.locator(css).bounding_box()


def test_after_a_pinch_what_was_between_the_fingers_is_between_them(doc):
    p = doc.page
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    b0 = box(p, STAGE)
    a = (b0["x"] + b0["width"] * 0.3, b0["y"] + b0["height"] * 0.5)
    b = (a[0] + 100, a[1])
    mid0 = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    u, v = (mid0[0] - b0["x"]) / b0["width"], (mid0[1] - b0["y"]) / b0["height"]
    p.evaluate(PTR, ["pointerdown", 1, *a])
    p.evaluate(PTR, ["pointerdown", 2, *b])
    a2, b2 = (a[0] + 70, a[1] + 30), (b[0] + 150, b[1] + 30)          # the fingers spread and the pair moves
    for t in (0.25, 0.5, 0.75, 1.0):
        p.evaluate(PTR, ["pointermove", 1, a[0] + (a2[0] - a[0]) * t, a[1] + (a2[1] - a[1]) * t])
        p.evaluate(PTR, ["pointermove", 2, b[0] + (b2[0] - b[0]) * t, b[1] + (b2[1] - b[1]) * t])
    p.evaluate(PTR, ["pointerup", 1, *a2])
    p.evaluate(PTR, ["pointerup", 2, *b2])
    b1 = box(p, STAGE)
    assert b1["width"] > b0["width"] * 1.2, "the pinch zoomed"
    mid1 = ((a2[0] + b2[0]) / 2, (a2[1] + b2[1]) / 2)
    assert abs((mid1[0] - b1["x"]) / b1["width"] - u) < 0.01 and abs((mid1[1] - b1["y"]) / b1["height"] - v) < 0.01


def test_a_pinch_that_does_not_spread_pans_by_the_midpoint_movement(doc):
    p = doc.page
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    b0 = box(p, STAGE)
    a = (b0["x"] + 100, b0["y"] + 100)
    b = (a[0] + 80, a[1])
    p.evaluate(PTR, ["pointerdown", 1, *a])
    p.evaluate(PTR, ["pointerdown", 2, *b])
    p.evaluate(PTR, ["pointermove", 1, a[0] + 40, a[1] + 10])
    p.evaluate(PTR, ["pointermove", 2, b[0] + 40, b[1] + 10])
    b1 = box(p, STAGE)
    assert abs(b1["width"] - b0["width"]) < 1
    assert round(b1["x"] - b0["x"]) == 40 and round(b1["y"] - b0["y"]) == 10, "moved once, not twice"


def test_the_legend_of_a_banded_chart_is_in_the_viewer(doc):
    p = doc.page
    assert p.locator("main .chart .bandleg").count() == 1
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    assert "on target" in p.inner_text("#rd-zoom .bandleg")
    b, g = box(p, STAGE), box(p, "#rd-zoom .bandleg")
    assert b["y"] + b["height"] <= g["y"] + 1, "the legend sits below the chart and does not cover it"


def test_a_chart_without_bands_opens_with_no_legend(tab, site):
    rewrite(site.file, '# Plan\n\n```chart\n{"type": "bar", "x": ["a", "b"], "series": [{"name": "S", "values": [1, 2]}]}\n```\n')
    p = tab.open().page
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    assert p.locator("#rd-zoom .bandleg").count() == 0


def test_a_click_on_an_xlink_link_in_an_svg_follows_the_link_and_opens_nothing(doc):
    p = doc.page
    p.click("main svg #hot")
    p.wait_for_timeout(200)
    assert p.locator(VIEWER).count() == 0
    assert p.evaluate("location.hash") == "#elsewhere"


def test_enter_on_a_focused_diagram_opens_the_viewer_and_escape_gives_the_focus_back(doc):
    p = doc.page
    p.focus("main .chart svg")
    p.keyboard.press("Enter")
    p.wait_for_selector(VIEWER)
    p.keyboard.press("Escape")
    until(lambda: p.locator(VIEWER).count() == 0, what="the viewer to close")
    assert p.evaluate("document.activeElement === document.querySelector('main .chart svg')")


def test_space_opens_an_svg_image_and_a_linked_svg_is_not_a_second_tab_stop(doc):
    p = doc.page
    p.focus("main img[alt='A round thing']")
    p.keyboard.press("Space")
    p.wait_for_selector(VIEWER)
    assert p.get_attribute("main img[alt='A round thing']", "role") == "button"
    p.keyboard.press("Escape")
    assert p.get_attribute("main svg:has(#hot)", "tabindex") is None, "a linked diagram has its link to tab to"


def test_a_diagram_taking_the_focus_does_not_make_a_block_dirty(doc):
    p = doc.page
    p.click("#rd-mode button")
    assert p.evaluate("document.querySelector('#rd-state').textContent") == "Editing", "the markings are no edit"
