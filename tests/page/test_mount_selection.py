"""Spike for the mountable page (#116 step 2): does text selection hold inside a CLOSED shadow root, in Chromium, Firefox and WebKit?

page.js anchors a comment on the member's selection (the quoted text, the block, the offsets), shows a popover beside it, and edits blocks in
place (contenteditable). Once the sheaf is mounted in the front's document instead of an iframe, it lives in a shadow root. `window.getSelection()`
retargets a selection inside a shadow tree to the host, so the page must read it with `Selection.getComposedRanges({shadowRoots: [root]})`.
This file asserts, in each engine, everything page.js asks of a selection. A browser not installed is skipped, never passed:
    uv run playwright install firefox webkit        (WebKit and Firefox need PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64 on 26.04)
"""
import json

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

PAGE = """<!doctype html><html><body>
<p id="outside">Light text outside the host.</p>
<div id="host"></div>
<script>
  const root = document.getElementById('host').attachShadow({mode: 'closed'});
  root.innerHTML = `
    <style>p,div{font:16px/24px sans-serif;margin:0;padding:4px} [contenteditable]{outline:0;min-height:30px}</style>
    <div id="doc">
      <p id="p1">The quick brown fox jumps over the lazy dog.</p>
      <p id="p2">A second paragraph with <em id="em">emphasis here</em> and <code id="code">code_span</code> inside.</p>
      <div id="edit" contenteditable="true">Edit me please</div>
    </div>`;
  window.__root = root;   // the test reads through it; the page keeps it in a closure
  window.__events = 0;
  document.addEventListener('selectionchange', () => { window.__events++; });
  // what page.js will use: the composed range of the selection inside the root, or null
  window.__sel = () => {
    const s = getSelection();
    if (!s.rangeCount) return null;
    if (typeof s.getComposedRanges !== 'function') return {noApi: true};
    const rs = s.getComposedRanges({shadowRoots: [root]});
    if (!rs.length) return null;
    const r = rs[0];
    const range = new Range();
    range.setStart(r.startContainer, r.startOffset);
    range.setEnd(r.endContainer, r.endOffset);
    const box = range.getBoundingClientRect();
    return {text: range.toString(), toString: s.toString(), collapsed: r.collapsed,
            startIn: root.contains(r.startContainer), endIn: root.contains(r.endContainer),
            startNode: r.startContainer.nodeName + '#' + (r.startContainer.parentNode && r.startContainer.parentNode.id || r.startContainer.id || ''),
            startOffset: r.startOffset, endOffset: r.endOffset, w: Math.round(box.width), h: Math.round(box.height)};
  };
</script></body></html>"""

ENGINES = ["chromium", "firefox", "webkit"]


@pytest.fixture(scope="module")
def pw():
    with sync_api.sync_playwright() as p:
        yield p


@pytest.fixture(params=ENGINES)
def page(request, pw):
    try:
        browser = getattr(pw, request.param).launch()
    except Exception as e:      # not installed, or its libraries are missing here
        pytest.skip(f"{request.param} cannot start here: {str(e).splitlines()[0]}")
    ctx = browser.new_context(viewport={"width": 900, "height": 700})
    pg = ctx.new_page()
    pg.set_content(PAGE)
    pg.engine = request.param
    yield pg
    browser.close()


def box(page, selector):
    """The viewport rect of an element inside the closed root."""
    return json.loads(page.evaluate("""s => { const r = window.__root.querySelector(s).getBoundingClientRect();
        return JSON.stringify({x: r.x, y: r.y, w: r.width, h: r.height}); }""", selector))


def word_point(page, selector, word, end=False):
    """Viewport (x, y) at the start or end of `word` in the text node of `selector`, from a Range, so a mouse drag lands there."""
    return json.loads(page.evaluate("""([s, word, end]) => {
        const el = window.__root.querySelector(s);
        const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        for (let n = w.nextNode(); n; n = w.nextNode()) {
          const i = n.data.indexOf(word);
          if (i < 0) continue;
          const r = new Range(); const at = i + (end ? word.length : 0);
          r.setStart(n, at); r.setEnd(n, at);
          const b = (end ? (() => { const q = new Range(); q.setStart(n, at - 1); q.setEnd(n, at); return q; })() : (() => { const q = new Range(); q.setStart(n, at); q.setEnd(n, at + 1); return q; })()).getBoundingClientRect();
          return JSON.stringify({x: end ? b.right : b.left, y: b.top + b.height / 2});
        }
        return 'null'; }""", [selector, word, end]))


def drag(page, a, b):
    page.mouse.move(a["x"], a["y"])
    page.mouse.down()
    page.mouse.move((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2, steps=4)
    page.mouse.move(b["x"], b["y"], steps=4)
    page.mouse.up()


def test_the_composed_range_api_exists(page):
    assert page.evaluate("typeof getSelection().getComposedRanges") == "function", page.engine


def test_a_mouse_drag_inside_one_block_gives_the_quoted_text_and_a_box(page):
    drag(page, word_point(page, "#p1", "quick"), word_point(page, "#p1", "fox", end=True))
    got = page.evaluate("window.__sel()")
    assert got and got["text"] == "quick brown fox", (page.engine, got)
    assert got["startIn"] and got["endIn"] and got["w"] > 40 and got["h"] > 8, (page.engine, got)
    assert page.evaluate("window.__events") > 0                 # selectionchange reaches the document's listener


def test_a_drag_across_two_blocks_and_through_inline_elements(page):
    drag(page, word_point(page, "#p1", "lazy"), word_point(page, "#p2", "emphasis", end=True))
    got = page.evaluate("window.__sel()")
    assert got and got["text"].replace("\n", " ").startswith("lazy dog.") and got["text"].endswith("emphasis"), (page.engine, got)
    assert got["startIn"] and got["endIn"], (page.engine, got)


def test_double_click_selects_a_word_and_triple_click_a_block(page):
    p = word_point(page, "#p1", "brown")
    page.mouse.dblclick(p["x"] + 4, p["y"])
    got = page.evaluate("window.__sel()")
    assert got and got["text"].strip() == "brown", (page.engine, got)
    page.mouse.click(p["x"] + 4, p["y"], click_count=3)
    got = page.evaluate("window.__sel()")
    assert got and got["text"].strip().startswith("The quick brown fox") and got["startIn"], (page.engine, got)


def test_a_selection_set_by_code_in_the_root_reads_back_the_same(page):
    page.evaluate("""() => { const t = window.__root.getElementById('p1').firstChild;
        getSelection().setBaseAndExtent(t, 4, t, 9); }""")
    got = page.evaluate("window.__sel()")
    assert got and got["text"] == "quick" and (got["startOffset"], got["endOffset"]) == (4, 9), (page.engine, got)


def test_the_range_can_be_wrapped_as_page_js_wraps_an_anchor(page):
    page.evaluate("""() => { const t = window.__root.getElementById('p1').firstChild;
        getSelection().setBaseAndExtent(t, 4, t, 9);
        const r = getSelection().getComposedRanges({shadowRoots: [window.__root]})[0];
        const range = new Range(); range.setStart(r.startContainer, r.startOffset); range.setEnd(r.endContainer, r.endOffset);
        const span = document.createElement('span'); span.id = 'anchor'; range.surroundContents(span); }""")
    assert page.evaluate("window.__root.getElementById('anchor').textContent") == "quick"
    assert page.evaluate("window.__root.getElementById('p1').textContent") == "The quick brown fox jumps over the lazy dog."


def test_a_contenteditable_block_takes_typing_and_reports_its_caret(page):
    e = box(page, "#edit")
    page.mouse.click(e["x"] + e["w"] - 10, e["y"] + e["h"] / 2)         # the caret at the end of the block
    page.keyboard.type(" now")
    assert page.evaluate("window.__root.getElementById('edit').textContent") == "Edit me please now", page.engine
    caret = page.evaluate("window.__sel()")
    assert caret and caret["collapsed"] and caret["startIn"] and caret["startOffset"] == len("Edit me please now"), (page.engine, caret)
    page.keyboard.press("Shift+ArrowLeft")
    page.keyboard.press("Shift+ArrowLeft")
    page.keyboard.press("Shift+ArrowLeft")
    assert page.evaluate("window.__sel()")["text"] == "now", page.engine
    page.keyboard.type("later")                                          # typing replaces the selection
    assert page.evaluate("window.__root.getElementById('edit').textContent") == "Edit me please later", page.engine


def test_focus_is_the_roots_own_and_the_host_is_what_the_document_sees(page):
    e = box(page, "#edit")
    page.mouse.click(e["x"] + 5, e["y"] + 5)
    assert page.evaluate("document.activeElement.id") == "host", page.engine      # retargeted for the front's scripts
    assert page.evaluate("window.__root.activeElement.id") == "edit", page.engine  # the page's own view


def test_a_selection_that_leaves_the_root_is_clipped_to_it_by_the_composed_range_or_flagged(page):
    """A drag from the light text into the root: page.js must not anchor a comment on text it does not own."""
    drag(page, {"x": 20, "y": box(page, "#p1")["y"] - 40}, word_point(page, "#p1", "quick", end=True))
    got = page.evaluate("window.__sel()")
    assert got is None or not (got["startIn"] and got["endIn"]) or got["text"].endswith("quick"), (page.engine, got)
    # the page's rule is `startIn and endIn`: a selection with an end outside the root is no comment anchor
    assert got is None or got["startIn"] is False or got["endIn"] is True, (page.engine, got)


# Measured 2026-10-31 (Chromium 145, Firefox 146, WebKit 26): Chromium and WebKit retarget the plain selection to a node of the light
# tree; Firefox does not, and hands out a node INSIDE the root. The page therefore always reads the composed range (the same answer
# in all three), and a closed root is no boundary against a script that reads the selection in Firefox: see the design note, section 4.
RETARGETS = {"chromium": True, "webkit": True, "firefox": False}


def test_control_the_plain_selection_is_retargeted_out_of_the_root_except_in_firefox(page):
    drag(page, word_point(page, "#p1", "quick"), word_point(page, "#p1", "fox", end=True))
    plain = page.evaluate("""() => { const s = getSelection(); return {anchor: s.anchorNode && s.anchorNode.nodeName,
        text: s.toString(), inRoot: s.anchorNode ? window.__root.contains(s.anchorNode) : null}; }""")
    assert (plain["inRoot"] is False) == RETARGETS[page.engine], (page.engine, plain)
    assert plain["text"] == "quick brown fox", (page.engine, plain)          # toString() alone does see through the root


def test_control_a_wrong_expectation_fails(page):
    """The spike would pass a broken reader: check it can fail."""
    drag(page, word_point(page, "#p1", "quick"), word_point(page, "#p1", "fox", end=True))
    got = page.evaluate("window.__sel()")
    assert got["text"] != "quick brown", (page.engine, got)
    assert (got["startOffset"], got["endOffset"]) == (4, 19), (page.engine, got)
