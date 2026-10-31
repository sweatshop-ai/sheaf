"""The sanitiser in MOUNT mode (#116 step 2, design note section 2).

Once the sheaf is mounted in the front's document the page's own CSP is gone, so what the sanitiser lets through is DOM in the
origin of a signed-in member. `sanitize(..., mount=True)` closes what that CSP used to close: script and event handlers as before,
and now also everything that phones home (an <img> on another host is a tracking pixel), the style attribute (it can overlay the
front's UI), SVG that loads or scripts, MathML, navigation to file:, and names that collide with the page's own.
The default mode is unchanged: the share copy and the loopback page keep their rules (tests/test_sanitize.py).

Every case also asserts what must SURVIVE, so a sanitiser that empties the document cannot pass."""
import re

import pytest

from sheafmd.sanitize import sanitize
from test_sanitize import names, tags_of, text_of


def mount(fragment: str) -> str:
    return sanitize(fragment, mount=True)


def attrs_of(out: str, tag: str):
    return [a for t, a in tags_of(out) if t == tag]


# ── execution ────────────────────────────────────────────────────────────────────

EXECUTES = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<a href=\"javascript:alert(1)\">x</a>",
    "<a href=\"java&#09;script:alert(1)\">x</a>",
    "<a href=\"&#x6A;avascript:alert(1)\">x</a>",
    "<a href=\"vbscript:msgbox(1)\">x</a>",
    "<a href=\"data:text/html,<script>alert(1)</script>\">x</a>",
    "<iframe src=\"https://evil.example/\"></iframe>",
    "<iframe srcdoc=\"<script>alert(1)</script>\"></iframe>",
    "<object data=\"x.swf\"></object>", "<embed src=\"x.swf\">", "<applet code=\"x\"></applet>",
    "<base href=\"https://evil.example/\">",
    "<form action=\"https://evil.example/\"><input name=a></form>",
    "<button formaction=\"https://evil.example/\">go</button>",
    "<textarea>x</textarea>", "<select><option>x</option></select>",
    "<template><script>alert(1)</script></template>",
    "<noscript><p title=\"</noscript><script>alert(1)</script>\"></noscript>",
    "<meta http-equiv=\"refresh\" content=\"0;url=https://evil.example/\">",
    "<link rel=\"stylesheet\" href=\"https://evil.example/x.css\">",
    "<link rel=\"prefetch\" href=\"https://evil.example/\">",
    "<style>@import 'https://evil.example/x.css';</style>",
    "<svg><script>alert(1)</script></svg>",
    "<svg><a xlink:href=\"javascript:alert(1)\"><text>x</text></a></svg>",
    "<svg><set attributeName=\"href\" to=\"javascript:alert(1)\"/></svg>",
    "<svg><animate attributeName=\"href\" values=\"javascript:alert(1)\"/></svg>",
    "<svg><animate attributeName=\"href\" from=\"a\" to=\"javascript:alert(1)\"/></svg>",
    "<svg onload=\"alert(1)\"></svg>",
    "<math><maction actiontype=\"statusline#\" xlink:href=\"javascript:alert(1)\">x</maction></math>",
    "<math><annotation-xml encoding=\"text/html\"><script>alert(1)</script></annotation-xml></math>",
    "<math href=\"javascript:alert(1)\"><mi>x</mi></math>",
    "<math><mglyph><style><img src=x onerror=alert(1)></style></mglyph></math>",
    "<svg><foreignObject><iframe src=\"https://evil.example/\"></iframe></foreignObject></svg>",
    "<svg><foreignObject><body onload=alert(1)></foreignObject></svg>",
    "<input type=image src=\"https://evil.example/x.png\">",
    "<details open ontoggle=alert(1)>x</details>",
    "<x-unknown onclick=\"alert(1)\">x</x-unknown>",
]

FORBIDDEN_TAGS = {"script", "style", "iframe", "frame", "object", "embed", "applet", "base", "meta", "link", "form", "button",
                  "textarea", "select", "template", "noscript", "math", "foreignobject", "use", "image", "set", "animate",
                  "animatemotion", "animatetransform", "input", "maction", "annotation-xml", "mglyph"}


def assert_inert(out: str):
    for tag, attrs in tags_of(out):
        assert tag not in FORBIDDEN_TAGS, (tag, out)
        for k, v in attrs.items():
            assert not k.startswith("on"), (k, out)
            assert k not in {"srcdoc", "formaction", "srcset", "ping", "target"}, (k, out)
            if k in {"href", "src", "xlink:href", "poster", "background", "action"}:
                scheme = re.sub(r"[\x00-\x20\x7f]+", "", v or "").lower()
                assert not scheme.startswith(("javascript:", "vbscript:", "data:text", "file:")), (k, v, out)


@pytest.mark.parametrize("payload", EXECUTES)
def test_nothing_that_can_run_survives_and_the_text_around_it_does(payload):
    out = mount(f"<p>before</p>{payload}<p>after</p>")
    assert_inert(out)
    assert "<p>before</p>" in out and "<p>after</p>" in out, out


def test_the_output_is_a_fixed_point_for_every_payload():
    for payload in EXECUTES:
        once = mount(f"<div>{payload}</div>")
        assert mount(once) == once, payload


# ── phone-home ────────────────────────────────────────────────────────────────────

REMOTE = [
    "<img src=\"https://evil.example/pixel.gif\" alt=\"x\">",
    "<img src=\"http://evil.example/pixel.gif\">",
    "<img src=\"//evil.example/pixel.gif\">",
    "<img src=\" https://evil.example/pixel.gif\">",
    "<img src=\"file:///etc/passwd\">",
    "<img src=\"data:image/svg+xml,<svg onload=alert(1)>\">",
    "<img src=\"data:text/html,x\">",
    "<img src=\"x.png\" srcset=\"https://evil.example/a.png 1x\">",
    "<video src=\"https://evil.example/v.mp4\" poster=\"https://evil.example/p.png\"></video>",
    "<audio src=\"https://evil.example/a.mp3\"></audio>",
    "<video><source src=\"https://evil.example/v.mp4\"><track src=\"https://evil.example/t.vtt\"></video>",
    "<picture><source srcset=\"https://evil.example/a.png\"><img src=\"x.png\"></picture>",
    "<svg><image href=\"https://evil.example/pixel.gif\"/></svg>",
    "<svg><image xlink:href=\"https://evil.example/pixel.gif\"/></svg>",
    "<svg><use href=\"https://evil.example/sprite.svg#a\"/></svg>",
    "<svg><use xlink:href=\"data:image/svg+xml;base64,PHN2Zy8+#a\"/></svg>",
    "<p style=\"background:url(https://evil.example/pixel.gif)\">x</p>",
    "<p style=\"background-image:image-set('https://evil.example/a.png' 1x)\">x</p>",
    "<p style=\"list-style:url(https://evil.example/a.png)\">x</p>",
    "<p style=\"background:u\\72l(https://evil.example/a.png)\">x</p>",
    "<p style=\"background:/**/url(https://evil.example/a.png)\">x</p>",
    "<div background=\"https://evil.example/a.png\">x</div>",
    "<a href=\"x.md\" ping=\"https://evil.example/ping\">x</a>",
]


@pytest.mark.parametrize("payload", REMOTE)
def test_nothing_that_loads_from_another_address_survives(payload):
    out = mount(f"<p>keep</p>{payload}")
    assert "evil.example" not in out and "/etc/passwd" not in out and "alert(1)" not in out, out
    assert "<p>keep</p>" in out


def test_an_image_the_page_may_show_stays():
    out = mount('<p><img src="data:image/png;base64,iVBORw0KGgo=" alt="a chart"><img src="figures/a.png" alt="b"><img src="a.png"></p>')
    srcs = [a["src"] for a in attrs_of(out, "img")]
    assert srcs == ["data:image/png;base64,iVBORw0KGgo=", "figures/a.png", "a.png"]


def test_a_dropped_image_leaves_its_alt_text_so_the_reader_still_sees_what_was_there():
    out = mount('<p>See <img src="https://evil.example/p.gif" alt="the Q3 chart"> here</p>')
    assert "img" not in names(out)
    assert "the Q3 chart" in text_of(out)


# ── navigation ────────────────────────────────────────────────────────────────────

def test_a_link_keeps_http_https_mailto_relative_and_fragment_and_no_other():
    ok = ['https://a.example/x', 'http://a.example/', 'mailto:a@b.example', 'other.md', '/list/x.md', '#sec', '?q=1']
    out = mount("".join(f'<a href="{u}">t</a>' for u in ok))
    assert [a["href"] for a in attrs_of(out, "a")] == ok
    for bad in ('file:///etc/passwd', 'FILE:///etc/passwd', 'tel:+3212345', 'sms:+3212345', 'ftp://a.example/x', 'blob:https://a.example/1',
                'about:blank', 'chrome://settings'):
        got = mount(f'<a href="{bad}">t</a>')
        assert not attrs_of(got, "a") or "href" not in attrs_of(got, "a")[0], bad
        assert "t" in text_of(got)


def test_every_link_leaves_without_telling_the_other_site_where_it_came_from_and_never_in_a_new_window():
    out = mount('<a href="https://a.example/" target="_blank" rel="opener">t</a><a href="x.md" target="_top">u</a><a href="#s">v</a>')
    for a in attrs_of(out, "a"):
        assert "target" not in a
        assert set(a["rel"].split()) >= {"noopener", "noreferrer"}, a


# ── the style attribute ───────────────────────────────────────────────────────────

OVERLAYS = [
    "position:fixed;top:0;left:0;width:100%;height:100%",
    "position:absolute;top:0",
    "position:sticky;top:0",
    "z-index:99999",
    "transform:scale(40)",
    "pointer-events:none",
    "font-size:900px",
    "content:'x'",
    "display:none",
    "visibility:hidden",
    "opacity:0",
    "-moz-binding:url(x.xml#a)",
    "behavior:url(x.htc)",
    "background:expression(alert(1))",
    "color:var(--x)",
    "width:calc(100vw + 1px)",
    "width:100vw",
    "margin:-9999px",
    "color:red !important",
    "color:red\\;position:fixed",
    "color:red;;;position:fixed",
    "colo\\72:red",
    "COLOR:red;POSITION:FIXED",
]


@pytest.mark.parametrize("decl", OVERLAYS)
def test_a_style_that_could_overlay_or_load_is_removed(decl):
    out = mount(f'<p style="{decl}">x</p>')
    style = (attrs_of(out, "p") or [{}])[0].get("style", "")
    assert not re.search(r"fixed|absolute|sticky|z-index|transform|pointer-events|expression|binding|behavior|var\(|calc\(|vw|!important|\\|content|display|visibility|opacity", style, re.I), (decl, style)
    assert "x" in text_of(out)


def test_the_plain_formatting_an_author_writes_stays():
    css = "text-align:center;color:#336699;background-color:rgb(250,250,200);font-weight:bold;font-style:italic;text-decoration:underline;width:50%"
    out = mount(f'<p style="{css}">x</p><td style="vertical-align:top;border:1px solid #ccc;padding:4px">y</td>')
    kept = attrs_of(out, "p")[0]["style"]
    for prop in ("text-align:center", "color:#336699", "font-weight:bold", "text-decoration:underline", "width:50%"):
        assert prop.replace(":", ": ") in kept or prop in kept, (prop, kept)
    assert "vertical-align" in attrs_of(out, "td")[0]["style"]


def test_one_bad_declaration_costs_only_itself():
    out = mount('<p style="color:red;position:fixed;font-weight:bold">x</p>')
    kept = attrs_of(out, "p")[0]["style"]
    assert "red" in kept and "bold" in kept and "fixed" not in kept


def test_a_style_with_nothing_left_has_no_style_attribute():
    assert "style" not in attrs_of(mount('<p style="position:fixed">x</p>'), "p")[0]


def test_svg_may_not_carry_a_style_that_a_html_element_may_not():
    out = mount('<svg><rect width="10" height="10" style="position:fixed;fill:url(https://evil.example/a#b)"/></svg>')
    assert "evil.example" not in out and "fixed" not in out


# ── SVG and MathML ────────────────────────────────────────────────────────────────

def test_a_small_svg_chart_survives():
    svg = ('<svg viewBox="0 0 100 50" width="200"><defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
           '<g><rect x="1" y="1" width="40" height="20" fill="#336699"/><circle cx="60" cy="20" r="10"/><path d="M0 0L10 10"/>'
           '<line x1="0" y1="0" x2="5" y2="5"/><polyline points="0,0 5,5"/><polygon points="0,0 5,5 9,0"/>'
           '<text x="5" y="45"><tspan>label</tspan></text><title>chart</title><desc>d</desc></g></svg>')
    out = mount(svg)
    assert {"svg", "g", "rect", "circle", "path", "line", "polyline", "polygon", "text", "tspan", "defs", "lineargradient", "stop", "title", "desc"} <= set(names(out))
    assert "label" in text_of(out)


@pytest.mark.parametrize("inner", ["<use href=\"#a\"/>", "<image href=\"a.png\"/>", "<foreignObject><p>x</p></foreignObject>",
                                  "<animate attributeName=\"x\" to=\"5\"/>", "<set attributeName=\"x\" to=\"5\"/>",
                                  "<animateTransform attributeName=\"transform\" to=\"1\"/>", "<animateMotion path=\"M0 0\"/>",
                                  "<a href=\"#a\"><text>t</text></a>"])
def test_svg_that_loads_references_or_moves_is_removed_even_when_the_target_is_local(inner):
    out = mount(f"<svg><rect width=\"5\" height=\"5\"/>{inner}</svg>")
    assert "rect" in names(out)
    assert not ({"use", "image", "foreignobject", "animate", "set", "animatetransform", "animatemotion"} & set(names(out))), out


def test_mathml_is_dropped_with_its_content_and_the_text_around_it_stays():
    out = mount("<p>if <math><mi>x</mi><mo>=</mo><mn>1</mn></math> then</p>")
    assert "math" not in names(out) and "mi" not in names(out)
    assert "if" in text_of(out) and "then" in text_of(out)


# ── names that collide with the page ──────────────────────────────────────────────

def test_an_author_class_or_attribute_in_the_pages_own_namespace_is_removed():
    out = mount('<div class="rd-popover keep" id="rd-popover" data-rd-ui="1" data-rd-id="b1" rd-x="1">x</div>')
    div = attrs_of(out, "div")[0]
    assert div.get("class") == "keep"
    assert not any(k.startswith(("data-rd", "rd-")) for k in div), div


def test_name_and_id_clobbering_attributes_are_not_kept_as_names():
    out = mount('<form name="x"></form><img name="getSelection" src="a.png"><a name="rd-popover">x</a><embed name="y">')
    assert not any("name" in a for a in attrs_of(out, "img") + attrs_of(out, "a")), out


def test_the_headings_ids_the_table_of_contents_links_to_stay():
    out = mount('<h2 id="why-it-works">Why</h2><p><a href="#why-it-works">up</a></p>')
    assert attrs_of(out, "h2")[0]["id"] == "why-it-works"
    assert attrs_of(out, "a")[0]["href"] == "#why-it-works"


# ── what the default mode still does ──────────────────────────────────────────────

def test_without_mount_the_old_rules_are_unchanged():
    out = sanitize('<p style="position:fixed">x</p><a href="file:///a/b.md" target="_blank">t</a><img src="https://a.example/p.png">')
    assert 'style="position:fixed"' in out and 'href="file:///a/b.md"' in out and "https://a.example/p.png" in out


# ── a short hostile run through the parser's known weak spots ─────────────────────

MUTATION = [
    "<svg></p><style><a id=\"</style><img src=1 onerror=alert(1)>\">",
    "<math><mtext><table><mglyph><style><!--</style><img title=\"--&gt;&lt;img src=1 onerror=alert(1)&gt;\">",
    "<noscript><style></noscript><img src=x onerror=alert(1)>",
    "<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>",
    "<svg><desc><![CDATA[</desc><script>alert(1)</script>]]></desc></svg>",
    "<p title=\"<script>alert(1)</script>\">x</p>",
    "<a href=\"x\" onclick = \"alert(1)\">x</a>",
    "<a/href=\"javascript:alert(1)\">x</a>",
    "<img/src=x/onerror=alert(1)>",
    "<!--><img src=x onerror=alert(1)>-->",
    "<![if true]><img src=x onerror=alert(1)><![endif]>",
]


@pytest.mark.parametrize("payload", MUTATION)
def test_known_mutation_payloads_leave_no_handler_and_no_script(payload):
    out = mount(payload)
    assert_inert(out)
    assert mount(out) == out
