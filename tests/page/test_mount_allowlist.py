"""The browser's side of the mounted page (#116 step 2, design note section 2 layer b): page/mount.js rebuilds the hub's text
from allow-lists, in real browsers, with the SERVER SANITISER LEFT OUT. This feeds the hostile corpus straight to
`sheafMount.rebuild` and asserts, in Chromium, Firefox and WebKit: no script ran, no request left the origin, no element or
attribute exists outside the lists, the page's own ids are untouched, and a hostile shape of the tree (very deep, very large)
neither throws nor hangs. The control runs the same corpus through `innerHTML` and must execute: it proves the harness can see
a failure. A browser that cannot start is skipped here and fails in CI (the page-test step turns a skip into a failure).
"""
import json
import time
from pathlib import Path

import pytest

import sheafmd

sync_api = pytest.importorskip("playwright.sync_api")

MOUNT_JS = (Path(sheafmd.__file__).parent / "page" / "mount.js").read_text(encoding="utf-8")
ORIGIN = "http://sheaf.test"
ENGINES = ["chromium", "firefox", "webkit"]

# Every payload sets a counter, or asks for a stranger's address. None of them is sanitised before it gets here.
PWN = "window.__pwned=(window.__pwned||0)+1"
HOSTILE = [
    f"<script>{PWN}</script>",
    f"<img src=x onerror=\"{PWN}\">",
    f"<svg onload=\"{PWN}\"></svg>",
    f"<a href=\"javascript:{PWN}\">x</a>",
    f"<a href=\"java&#09;script:{PWN}\">x</a>",
    f"<a href=\"data:text/html,<script>{PWN}</script>\">x</a>",
    f"<iframe srcdoc=\"<script>parent.{PWN}</script>\"></iframe>",
    "<iframe src=\"http://evil.test/frame\"></iframe>",
    "<object data=\"http://evil.test/o\"></object><embed src=\"http://evil.test/e\">",
    "<base href=\"http://evil.test/\"><a href=\"x\">rel</a>",
    "<link rel=stylesheet href=\"http://evil.test/x.css\"><link rel=prefetch href=\"http://evil.test/p\">",
    "<style>@import 'http://evil.test/x.css'; p{background:url(http://evil.test/bg.png)}</style>",
    "<meta http-equiv=refresh content=\"0;url=http://evil.test/\">",
    "<img src=\"http://evil.test/pixel.gif\" alt=\"pixel\">",
    "<img src=\"//evil.test/pixel.gif\"><img src=\"\\\\evil.test/pixel.gif\">",
    "<img src=\"x.png\" srcset=\"http://evil.test/a.png 1x\">",
    "<video src=\"http://evil.test/v\" poster=\"http://evil.test/p\"></video><audio src=\"http://evil.test/a\"></audio>",
    "<picture><source srcset=\"http://evil.test/a.png\"><img src=\"http://evil.test/b.png\"></picture>",
    "<p style=\"background:url(http://evil.test/bg.png)\">x</p>",
    "<p style=\"position:fixed;top:0;left:0;width:100%;height:100%;background:red\">overlay</p>",
    "<p style=\"background-image:image-set('http://evil.test/a.png' 1x)\">x</p>",
    "<table background=\"http://evil.test/bg.png\"><tr><td background=\"http://evil.test/c.png\">x</td></tr></table>",
    "<form action=\"http://evil.test/post\"><input name=a value=b><button>go</button></form>",
    "<input type=image src=\"http://evil.test/i.png\">",
    "<svg><use href=\"http://evil.test/s.svg#a\"/><image href=\"http://evil.test/i.png\"/></svg>",
    f"<svg><a xlink:href=\"javascript:{PWN}\"><text>x</text></a></svg>",
    f"<svg><set attributeName=\"href\" to=\"javascript:{PWN}\"/><animate attributeName=\"href\" values=\"javascript:{PWN}\"/></svg>",
    f"<svg><foreignObject><iframe src=\"javascript:{PWN}\"></iframe><img src=x onerror=\"{PWN}\"></foreignObject></svg>",
    f"<svg><script>{PWN}</script></svg>",
    f"<svg></p><style><a id=\"</style><img src=1 onerror={PWN}>\">",
    f"<math><mtext><table><mglyph><style><!--</style><img title=\"--&gt;&lt;img src=1 onerror={PWN}&gt;\">",
    f"<math><maction actiontype=\"statusline#\" xlink:href=\"javascript:{PWN}\">x</maction></math>",
    f"<math><annotation-xml encoding=\"text/html\"><script>{PWN}</script></annotation-xml></math>",
    f"<noscript><p title=\"</noscript><img src=x onerror={PWN}>\"></noscript>",
    f"<template><script>{PWN}</script><img src=x onerror=\"{PWN}\"></template>",
    f"<form><math><mtext></form><form><mglyph><style></math><img src onerror={PWN}>",
    f"<!--><img src=x onerror={PWN}>-->",
    f"<![if true]><img src=x onerror={PWN}><![endif]>",
    f"<details open ontoggle=\"{PWN}\">x</details>",
    f"<x-unknown onclick=\"{PWN}\" onfocus=\"{PWN}\" tabindex=0>x</x-unknown>",
    f"<a/href=\"javascript:{PWN}\">x</a><img/src=x/onerror={PWN}>",
    "<div id=\"rd-popover\" class=\"rd-popover keep\" data-rd-ui=\"1\">clash</div>",
    "<a name=\"getSelection\" id=\"__proto__\">x</a><img name=\"localStorage\" id=\"constructor\" src=\"a.png\">",
]

# What may exist in the result, written out again here so a change to the lists in mount.js is a change to this file too.
HTML_OK = set("""a abbr address article aside b bdi bdo blockquote br caption cite code col colgroup dd del details dfn div dl dt em
    figcaption figure footer h1 h2 h3 h4 h5 h6 header hr i img input ins kbd li main mark nav ol p pre q rp rt ruby s samp section
    small span strong sub summary sup table tbody td tfoot th thead time tr u ul var wbr""".split())
SVG_OK = set("svg g path rect circle ellipse line polyline polygon text tspan defs lineargradient stop title desc".split())
ATTR_OK = set("""id class title lang dir href src alt width height colspan rowspan align valign scope span start reversed type value
    open datetime checked disabled border style rel viewbox x y x1 y1 x2 y2 cx cy r rx ry d points fill stroke stroke-width
    stroke-linecap stroke-linejoin stroke-dasharray stroke-opacity fill-opacity opacity font-size font-weight font-style
    text-anchor dominant-baseline offset stop-color stop-opacity gradientunits gradienttransform transform preserveaspectratio""".split())


# Payloads that open math, a comment, a conditional or a raw-text element and never close it: the HTML parser puts the rest of the
# document inside, in every browser, before mount.js sees a node. Server side, render.py reports it ("is never closed").
OPENS_FOREIGN_CONTENT = ("<math", "<!--", "<![if", "<svg></p>", "<noscript>", "<template>", "<form><math")


@pytest.fixture(scope="module")
def pw():
    with sync_api.sync_playwright() as p:
        yield p


@pytest.fixture(params=ENGINES)
def env(request, pw):
    try:
        browser = getattr(pw, request.param).launch()
    except Exception as e:      # not installed, or its libraries are missing here
        pytest.skip(f"{request.param} cannot start here: {str(e).splitlines()[0]}")
    ctx = browser.new_context()
    page = ctx.new_page()
    seen = []

    def route(r):
        url = r.request.url
        seen.append(url)
        if url == ORIGIN + "/":
            return r.fulfill(content_type="text/html", body="<!doctype html><title>t</title><body><div id=\"host\"></div></body>")
        if url.startswith(ORIGIN):
            return r.fulfill(status=200, content_type="image/png", body=b"")
        return r.abort()         # a stranger's address: the request is counted above, and it goes nowhere

    page.route("**/*", route)
    page.goto(ORIGIN + "/")
    page.add_script_tag(content=MOUNT_JS)
    page.engine, page.seen = request.param, seen
    yield page
    browser.close()


def strangers(page):
    return [u for u in page.seen if not u.startswith(ORIGIN) and not u.startswith("data:") and not u.startswith("about:")]


def inventory(page, root_expr="document.getElementById('out')"):
    """Every element under the rebuilt tree: tag (namespace-aware, lower case) and its attribute names and values."""
    return page.evaluate("""(sel) => { const root = eval(sel); const out = [];
        for (const el of root.querySelectorAll('*')) out.push({tag: el.localName.toLowerCase(), ns: el.namespaceURI,
            attrs: Array.from(el.attributes).map(a => [a.name, a.value, a.namespaceURI])});
        return out; }""", root_expr)


def rebuild_into_page(page, html):
    page.evaluate("""(html) => { const out = document.createElement('div'); out.id = 'out'; document.body.append(out);
        out.append(sheafMount.rebuild(html, out)); }""", html)


def assert_in_the_lists(page):
    for el in inventory(page):
        ok = HTML_OK if el["ns"] == "http://www.w3.org/1999/xhtml" else SVG_OK
        assert el["tag"] in ok, (page.engine, el)
        for name, value, ns in el["attrs"]:
            assert ns is None and name.lower() in ATTR_OK, (page.engine, el["tag"], name)
            assert not name.lower().startswith("on"), (page.engine, el)
            if name in ("href", "src"):
                assert not value.strip().lower().startswith(("javascript", "data:text", "vbscript", "file")), (page.engine, el)
            if name == "style":
                assert "url(" not in value and "fixed" not in value and "absolute" not in value, (page.engine, el)


@pytest.mark.parametrize("payload", HOSTILE, ids=[f"{i:02d}" for i in range(len(HOSTILE))])
def test_a_hostile_payload_runs_nothing_loads_nothing_and_leaves_only_what_the_lists_name(env, payload):
    rebuild_into_page(env, f"<p>before</p>{payload}<p>after</p>")
    env.wait_for_timeout(250)                       # a handler, an image or a frame gets its turn
    assert env.evaluate("window.__pwned || 0") == 0, (env.engine, payload)
    assert strangers(env) == [], (env.engine, strangers(env))
    assert_in_the_lists(env)
    text = env.evaluate("document.getElementById('out').textContent")
    assert "before" in text, (env.engine, text)
    if not any(k in payload for k in OPENS_FOREIGN_CONTENT):       # the browser's own parser ends these only at the end of the text
        assert "after" in text, (env.engine, text)


def test_the_whole_corpus_in_one_document_runs_nothing(env):
    rebuild_into_page(env, "".join(HOSTILE))
    env.wait_for_timeout(400)
    assert env.evaluate("window.__pwned || 0") == 0 and strangers(env) == [], (env.engine, strangers(env))
    assert_in_the_lists(env)


def test_control_the_same_corpus_through_innerHTML_does_run_and_does_load(env):
    """The harness can see a failure: the naive way to mount the text executes it and reaches the stranger's address."""
    env.evaluate("""(html) => { const d = document.createElement('div'); document.body.append(d); d.innerHTML = html; }""", "".join(HOSTILE))
    env.wait_for_timeout(600)
    assert env.evaluate("window.__pwned || 0") > 0 or strangers(env), env.engine


def test_a_dropped_image_leaves_its_alt_text(env):
    rebuild_into_page(env, '<p>See <img src="http://evil.test/p.gif" alt="the Q3 chart"> here</p>')
    assert env.evaluate("document.getElementById('out').textContent") == "See the Q3 chart here"
    assert env.evaluate("document.querySelectorAll('#out img').length") == 0


def test_the_page_can_still_show_what_a_sheaf_holds(env):
    html = ('<nav id="toc"><a class="lv2" href="#why">Why</a></nav><main><h2 id="why">Why</h2>'
            '<p>Text with <strong>bold</strong>, <em>emphasis</em>, <code>code</code> and <a href="https://example.com/x" target="_blank">a link</a>'
            ' and <a href="other.md">another</a>.</p><!--rd:b1-->'
            '<table><thead><tr><th scope="col" style="text-align:center">A</th></tr></thead><tbody><tr><td colspan="2" style="color:#336699">1</td></tr></tbody></table>'
            '<ul><li><input type="checkbox" checked disabled> done</li><li><input type="text" value="no"> typed</li></ul>'
            '<img src="data:image/png;base64,iVBORw0KGgo=" alt="chart"><img src="figures/a.png" alt="b">'
            '<svg viewBox="0 0 100 50" width="200"><defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
            '<rect x="1" y="1" width="40" height="20" fill="url(#g)"/><text x="5" y="45">label</text></svg></main>')
    rebuild_into_page(env, html)
    got = env.evaluate("""() => { const o = document.getElementById('out'); const q = (s) => o.querySelector(s);
        return {h2: q('h2').id, toc: q('#u-toc a').getAttribute('href'), link: q('a[href^=https]').getAttribute('rel'),
                target: q('a[href^=https]').hasAttribute('target'), other: q('a[href="other.md"]') !== null,
                th: q('th').getAttribute('style'), td: q('td').getAttribute('colspan'), boxes: o.querySelectorAll('input').length,
                box: q('input').checked + '/' + q('input').disabled, images: Array.from(o.querySelectorAll('img')).map(i => i.getAttribute('src')),
                svg: q('svg').namespaceURI, rect: q('rect').getAttribute('fill'), grad: q('linearGradient').id,
                comment: Array.from(o.querySelectorAll('main')[0].childNodes).some(n => n.nodeType === 8 && n.data === 'rd:b1'),
                text: o.textContent}; }""")
    assert got["h2"] == "u-why" and got["toc"] == "#u-why"                      # the id and the link to it move together
    assert got["link"] == "noopener noreferrer" and got["target"] is False and got["other"]
    assert got["th"] == "text-align:center" and got["td"] == "2"
    assert got["boxes"] == 1 and got["box"] == "true/true"                       # the checkbox stays, the text input does not
    assert got["images"] == ["data:image/png;base64,iVBORw0KGgo=", "figures/a.png"]
    assert got["svg"] == "http://www.w3.org/2000/svg" and got["rect"] == "url(#u-g)" and got["grad"] == "u-g"
    assert got["comment"] is True and "label" in got["text"] and "typed" in got["text"]


def test_an_author_name_cannot_take_a_name_the_page_uses(env):
    env.evaluate("""() => { const host = document.getElementById('host'); const root = host.attachShadow({mode: 'open'});
        root.innerHTML = '<div id="rd-popover">the page\\'s own</div>';
        root.append(sheafMount.rebuild('<div id="rd-popover" class="rd-popover keep" data-rd-ui="1">clash</div><a id="x" name="getSelection">n</a>', root));
        window.__root = root; }""")
    got = env.evaluate("""() => { const r = window.__root;
        return {own: r.getElementById('rd-popover').textContent, clash: r.querySelectorAll('.rd-popover').length,
                ids: Array.from(r.querySelectorAll('[id]')).map(e => e.id), sel: typeof getSelection, ds: document.querySelector('[data-rd-ui]')}; }""")
    assert got["own"] == "the page's own" and got["clash"] == 0 and got["sel"] == "function" and got["ds"] is None
    assert sorted(got["ids"]) == ["rd-popover", "u-x"]


def test_a_document_nested_deep_but_not_absurdly_keeps_its_text_and_stops_nesting_at_the_limit(env):
    deep = "<div>" * 1400 + "deep text" + "</div>" * 1400
    t0 = time.monotonic()
    rebuild_into_page(env, "<p>start</p>" + deep + "<p>end</p>")
    assert time.monotonic() - t0 < 10, env.engine
    text = env.evaluate("document.getElementById('out').textContent")
    assert "start" in text and "end" in text and "deep text" in text, (env.engine, text[:80])
    assert env.evaluate("(() => { let d = 0, e = document.querySelector('#out > div'); for (; e; e = e.firstElementChild) d++; return d; })()") <= 61


@pytest.mark.parametrize("shape", ["<div>", "<div/>", "<span>", "<b><i>"])
def test_a_document_nested_a_hundred_thousand_deep_is_refused_at_once_not_parsed(env, shape):
    """DOMParser costs the square of the depth: 20 s in Chromium for this. The scan before it refuses in milliseconds."""
    t0 = time.monotonic()
    rebuild_into_page(env, "<p>start</p>" + shape * 100000 + "deep text")
    assert time.monotonic() - t0 < 5, env.engine
    text = env.evaluate("document.getElementById('out').textContent")
    assert "nested too deeply" in text and "deep text" not in text, (env.engine, text[:80])
    assert env.evaluate("document.querySelectorAll('#out *').length") == 1


def test_a_big_svg_of_self_closing_shapes_is_not_mistaken_for_deep_nesting(env):
    rebuild_into_page(env, "<svg viewBox=\"0 0 10 10\">" + "<rect x=\"1\" y=\"1\" width=\"1\" height=\"1\"/>" * 5000 + "</svg>")
    assert env.evaluate("document.querySelectorAll('#out rect').length") == 5000


def test_a_document_of_a_million_nodes_is_cut_off_and_says_so(env):
    env.evaluate("""() => { const o = document.createElement('div'); o.id = 'out'; document.body.append(o);
        const f = sheafMount.rebuild('<p>x</p>'.repeat(250000), o); window.__stats = f.sheafStats; o.append(f); }""")
    stats = env.evaluate("window.__stats")
    assert stats["truncated"] is True and stats["nodes"] <= 200000, (env.engine, stats)


def test_mount_builds_a_closed_root_from_the_hubs_answer_and_nothing_reaches_it_from_outside(env):
    answer = {"title": "T", "toc": False, "version": "1.0.1", "css": "p{color:#111}", "config": {"name": "t.md"},
              "html": "<h1 id=\"t\">T</h1><p>body</p><img src=\"http://evil.test/p.gif\" alt=\"px\"><script>" + PWN + "</script>"}
    env.route(ORIGIN + "/_/mount*", lambda r: r.fulfill(content_type="application/json", body=json.dumps(answer)))
    env.route(ORIGIN + "/_/mount.css*", lambda r: r.fulfill(content_type="text/css", body=":host{display:block}"))
    env.evaluate("""() => { const real = Element.prototype.attachShadow; window.__roots = [];
        Element.prototype.attachShadow = function (init) { const r = real.call(this, init); window.__roots.push(r); return r; }; }""")
    got = env.evaluate("""async () => { const host = document.getElementById('host');
        const m = await sheafMount.mount(host, {doc: 'work/t.md'});
        const root = window.__roots[0];
        return {closed: host.shadowRoot === null, text: root.textContent, h1: root.querySelector('h1').id, img: root.querySelectorAll('img').length,
                script: root.querySelectorAll('script').length, css: root.querySelector('style').textContent, title: m.title}; }""")
    env.wait_for_timeout(250)
    assert got["closed"] is True and got["h1"] == "u-t" and got["img"] == 0 and got["script"] == 0, (env.engine, got)
    assert "body" in got["text"] and "px" in got["text"] and got["css"] == "p{color:#111}"
    assert env.evaluate("window.__pwned || 0") == 0 and strangers(env) == [], (env.engine, strangers(env))
