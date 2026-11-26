"""A diagram or an SVG image opens in a viewer of the whole window (SPEC 6.9): wheel and pinch zoom about the
pointer, drag to pan, a reset, and Esc, a close button or a click outside to close. It works in Comment and in Edit
mode (a click on a diagram edits nothing), on a phone, and in both colour schemes."""
import pytest

from pagehelp import until, rewrite, key

pytestmark = pytest.mark.page

VIEWER = "#rd-zoom"
STAGE = "#rd-zoom .rd-zoom-stage"
CLOSE = "#rd-zoom .rd-zoom-close"
RESET = "#rd-zoom .rd-zoom-reset"
TOGGLE = "#rd-mode button"
CHART = ('```chart\n{"type": "bar", "x": ["north", "south", "east"],\n'
         ' "series": [{"name": "Sales", "values": [10, 20, 30]}]}\n```\n')
PIC = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">'
       '<rect width="200" height="100" fill="#fde68a"/><circle cx="100" cy="50" r="30" fill="#b45309"/></svg>')
MD = f"# Plan\n\nBefore the chart.\n\n{CHART}\nBetween.\n\n![A round thing](pic.svg)\n\nAfter.\n"


@pytest.fixture
def doc(tab, site):
    (site.file.parent / "pic.svg").write_text(PIC)
    rewrite(site.file, MD)
    return tab.open()


def opened(p):
    return p.locator(VIEWER).count() == 1


def scale(p):
    return float(p.get_attribute(STAGE, "data-k"))


def box(p, css):
    return p.locator(css).bounding_box()


def centre(b):
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def test_a_click_on_a_chart_opens_the_viewer_and_escape_closes_it(doc):
    p = doc.page
    assert not opened(p)
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    assert p.locator(f"{STAGE} svg").count() == 1
    p.keyboard.press("Escape")
    until(lambda: not opened(p), what="the viewer to close")


def test_a_click_on_an_svg_image_opens_it_too(doc):
    p = doc.page
    p.click("main img[alt='A round thing']")
    p.wait_for_selector(VIEWER)
    assert p.locator(f"{STAGE} img").count() == 1


def test_the_close_button_and_a_click_outside_close_it_and_a_click_on_the_diagram_does_not(doc):
    p = doc.page
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    p.mouse.click(*centre(box(p, STAGE)))
    assert opened(p)
    p.click(CLOSE)
    until(lambda: not opened(p), what="the close button")
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    p.mouse.click(4, 4)
    until(lambda: not opened(p), what="a click outside")


def test_the_wheel_zooms_about_the_pointer(doc):
    p = doc.page
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    b0 = box(p, STAGE)
    px, py = b0["x"] + b0["width"] * 0.25, b0["y"] + b0["height"] * 0.25
    k0 = scale(p)
    p.mouse.move(px, py)
    p.mouse.wheel(0, -400)
    until(lambda: scale(p) > k0, what="zoom in")
    b1 = box(p, STAGE)
    assert b1["width"] > b0["width"] * 1.2
    assert abs((px - b1["x"]) / b1["width"] - 0.25) < 0.01      # the point under the pointer stayed under it
    assert abs((py - b1["y"]) / b1["height"] - 0.25) < 0.01
    p.mouse.wheel(0, 4000)
    until(lambda: scale(p) < k0 * 1.01, what="zoom out")
    assert scale(p) >= 0.4                                        # and it stops somewhere


def test_dragging_pans_and_the_reset_button_and_a_double_click_bring_it_back(doc):
    p = doc.page
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    b0 = box(p, STAGE)
    p.mouse.move(*centre(b0))
    p.mouse.wheel(0, -600)
    until(lambda: scale(p) > 1.2, what="zoom in")
    b1 = box(p, STAGE)
    x, y = centre(b1)
    p.mouse.move(x, y)
    p.mouse.down()
    p.mouse.move(x + 60, y + 40, steps=5)
    p.mouse.up()
    b2 = box(p, STAGE)
    assert round(b2["x"] - b1["x"]) == 60 and round(b2["y"] - b1["y"]) == 40
    assert opened(p), "a drag is not a click outside"
    p.click(RESET)
    until(lambda: abs(scale(p) - 1) < 0.001, what="reset")
    assert abs(box(p, STAGE)["x"] - b0["x"]) < 1
    p.mouse.move(*centre(b0))
    p.mouse.wheel(0, -600)
    until(lambda: scale(p) > 1.2, what="zoom in again")
    p.mouse.dblclick(*centre(box(p, STAGE)))
    until(lambda: abs(scale(p) - 1) < 0.001, what="reset by double click")
    assert opened(p)


def test_in_edit_mode_a_click_on_a_chart_opens_it_and_edits_nothing(doc):
    p = doc.page
    p.click(TOGGLE)
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    p.keyboard.press("Escape")
    until(lambda: not opened(p), what="the viewer to close")
    assert p.evaluate("document.body.classList.contains('rd-editing')"), "Esc closed the viewer, not edit mode"
    assert p.inner_text(TOGGLE).startswith("Save")
    p.click("main p:has-text(\"Before the chart\")")      # text is still edited where it is text
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" and more")
    assert "Before the chart. and more" in p.inner_text("main")


def test_a_dark_page_gets_a_viewer_with_a_visible_diagram(tab, site):
    (site.file.parent / "pic.svg").write_text(PIC)
    rewrite(site.file, MD)
    tab.page.emulate_media(color_scheme="dark")
    p = tab.open().page
    p.click("main .chart svg")
    p.wait_for_selector(VIEWER)
    bg = p.evaluate(f"getComputedStyle(document.querySelector('{STAGE}')).backgroundColor")
    assert bg not in ("rgba(0, 0, 0, 0)", "transparent")


def test_on_a_phone_a_tap_opens_it_and_a_tap_on_the_button_closes_it(touch_tab, site):
    (site.file.parent / "pic.svg").write_text(PIC)
    rewrite(site.file, MD)
    p = touch_tab.open().page
    p.tap("main .chart svg")
    p.wait_for_selector(VIEWER)
    b = box(p, STAGE)
    assert b["width"] <= 390
    p.tap(CLOSE)
    until(lambda: not opened(p), what="the close button")
