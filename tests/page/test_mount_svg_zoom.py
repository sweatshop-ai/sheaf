"""The diagram viewer on a page mounted in a pane of the front's document (SPEC 6.9, #116). The viewer is the pane's, not the
window's: a pane narrower than the window and away from its corner is where it fits the diagram and where a zoom about the
pointer is measured. A local SVG image reaches the mounted page as a base64 data address, which the page's own sanitiser
must keep for the viewer to have an image to open. A page test: it runs in CI only."""
import pytest
from pagehelp import rewrite, until

from test_mount_page import front  # noqa: F401  (fixture)
from test_mount_allowlist import env, pw, rebuild_into_page  # noqa: F401  (fixtures)

pytestmark = pytest.mark.page

CHART = ('```chart\n{"type": "bar", "x": ["north", "south", "east"],\n'
         ' "series": [{"name": "Sales", "values": [10, 20, 30]}]}\n```\n')
PIC = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">'
       '<rect width="200" height="100" fill="#fde68a"/><circle cx="100" cy="50" r="30" fill="#b45309"/></svg>')
MD = f"# Plan\n\nBefore the chart.\n\n{CHART}\nBetween.\n\n![A round thing](pic.svg)\n\nAfter.\n"
VIEWER, STAGE = "#rd-zoom", "#rd-zoom .rd-zoom-stage"
NARROW = "const p = document.getElementById('pane'); p.style.width = '420px'; p.style.marginLeft = '380px';"


@pytest.fixture
def mounted(front, site):  # noqa: F811
    (site.file.parent / "pic.svg").write_text(PIC)
    rewrite(site.file, MD)
    f = front.open()
    f.page.evaluate("() => { " + NARROW + " }")
    return f


def rect(f, css):
    return f.js("const r = root.querySelector(arg).getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height};", css)


def inside(inner, outer, slack=1):
    return (inner["x"] >= outer["x"] - slack and inner["y"] >= outer["y"] - slack
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + slack
            and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + slack)


def test_in_a_narrow_pane_the_viewer_opens_with_the_whole_diagram_inside_the_pane(mounted):
    f = mounted
    f.click("main .chart svg")
    until(lambda: f.has(VIEWER), what="the viewer")
    pane = f.page.evaluate("(() => { const r = document.getElementById('pane').getBoundingClientRect(); "
                           "return {x: r.x, y: r.y, w: r.width, h: r.height}; })()")
    assert inside(rect(f, STAGE), pane), (rect(f, STAGE), pane)
    f.page.evaluate("() => { document.getElementById('pane').style.width = '300px'; }")     # a window made smaller
    f.click("#rd-zoom .rd-zoom-reset")
    pane = f.page.evaluate("(() => { const r = document.getElementById('pane').getBoundingClientRect(); "
                           "return {x: r.x, y: r.y, w: r.width, h: r.height}; })()")
    assert inside(rect(f, STAGE), pane), "Fit measures the pane, not the window"


def test_in_an_offset_pane_the_wheel_zooms_about_the_pointer(mounted):
    f = mounted
    f.click("main .chart svg")
    until(lambda: f.has(VIEWER), what="the viewer")
    b0 = rect(f, STAGE)
    px, py = b0["x"] + b0["w"] * 0.25, b0["y"] + b0["h"] * 0.25
    f.page.mouse.move(px, py)
    f.page.mouse.wheel(0, -400)
    until(lambda: rect(f, STAGE)["w"] > b0["w"] * 1.2, what="zoom in")
    b1 = rect(f, STAGE)
    assert abs((px - b1["x"]) / b1["w"] - 0.25) < 0.01 and abs((py - b1["y"]) / b1["h"] - 0.25) < 0.01


def test_the_buttons_zoom_about_the_middle_of_the_pane(mounted):
    f = mounted
    f.click("main .chart svg")
    until(lambda: f.has(VIEWER), what="the viewer")
    pane = f.page.evaluate("(() => { const r = document.getElementById('pane').getBoundingClientRect(); "
                           "return [r.x + r.width / 2, r.y + r.height / 2]; })()")
    b0 = rect(f, STAGE)
    u0, v0 = (pane[0] - b0["x"]) / b0["w"], (pane[1] - b0["y"]) / b0["h"]
    f.click("#rd-zoom .rd-zoom-in")
    until(lambda: rect(f, STAGE)["w"] > b0["w"] * 1.2, what="zoom in")
    b1 = rect(f, STAGE)
    assert abs((pane[0] - b1["x"]) / b1["w"] - u0) < 0.01 and abs((pane[1] - b1["y"]) / b1["h"] - v0) < 0.01


def test_a_local_svg_image_on_a_mounted_page_opens_in_the_viewer(mounted):
    f = mounted
    assert f.js("return root.querySelectorAll('main img[alt=\"A round thing\"]').length;") == 1, "the image is kept"
    f.click("main img[alt='A round thing']")
    until(lambda: f.has(VIEWER), what="the viewer")
    assert f.js("return root.querySelectorAll('#rd-zoom img').length;") == 1


def test_the_page_script_keeps_an_svg_image_and_nothing_else_of_that_kind(env):  # noqa: F811
    svg = "data:image/svg+xml;base64,PHN2Zy8+"
    rebuild_into_page(env, f'<p><img src="{svg}" alt="kept"></p>'
                           '<p><img src="data:image/svg+xml,&lt;svg onload=alert(1)&gt;" alt="dropped one"></p>'
                           '<p><img src="data:image/svg+xml;charset=utf-8;base64,PHN2Zy8+" alt="dropped two"></p>')
    got = env.evaluate("Array.from(document.querySelectorAll('#out img')).map(i => i.getAttribute('src'))")
    assert got == [svg], (env.engine, got)
