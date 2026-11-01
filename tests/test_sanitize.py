"""The raw-HTML sanitiser (SPEC 9.5, tests of SPEC 18 Security): each item removed,
task boxes and comments kept.

Every removal test also asserts what must SURVIVE next to it, so a sanitiser that
empties the document cannot pass."""
import random
from html.parser import HTMLParser

import pytest

from sheafmd.sanitize import ALSO_REMOVED, DROPPED_ATTRS, REMOVE, URL_ATTRS, sanitize


def tags_of(out: str):
    """(tag, {attr: value}) for every start tag, read by the standard library's own
    parser, independent of the one the sanitiser uses to rebuild the document."""
    found = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            found.append((tag, dict(attrs)))
        handle_startendtag = handle_starttag
    P(convert_charrefs=True).feed(out)
    return found


def text_of(out: str) -> str:
    chunks = []

    class P(HTMLParser):
        def handle_data(self, data):
            chunks.append(data)
    P(convert_charrefs=True).feed(out)
    return "".join(chunks)


def names(out):
    return [t for t, _ in tags_of(out)]


# ── elements removed with their content ─────────────────────────────────────

CONTENT = {
    "script": "<script>alert('X-SCRIPT')</script>",
    "style": "<style>body{background:url(http://x.example/X-STYLE)}</style>",
    "iframe": "<iframe src='http://x.example/'>X-IFRAME</iframe>",
    "frame": "<frame src='http://x.example/'>",
    "frameset": "<frameset><frame src='http://x.example/'>X-FRAMESET</frameset>",
    "object": "<object data='http://x.example/'>X-OBJECT</object>",
    "embed": "<embed src='http://x.example/x.swf'>",
    "applet": "<applet code='X.class'>X-APPLET</applet>",
    "base": "<base href='http://x.example/'>",
    "meta": "<meta http-equiv='refresh' content='0;url=http://x.example/'>",
    "link": "<link rel='stylesheet' href='http://x.example/x.css'>",
    "form": "<form action='http://x.example/'>X-FORM</form>",
    "button": "<button>X-BUTTON</button>",
    "textarea": "<textarea>X-TEXTAREA</textarea>",
    "select": "<select><option>X-SELECT</option></select>",
    "template": "<template><img src=x onerror=1>X-TEMPLATE</template>",
    "noscript": "<noscript><p title='</noscript><img src=x onerror=1>'>X-NOSCRIPT</p></noscript>",
}


def test_the_table_covers_every_element_of_the_spec():
    assert set(CONTENT) == set(REMOVE)


@pytest.mark.parametrize("tag", sorted(CONTENT))
def test_each_listed_element_goes_with_its_content(tag):
    out = sanitize(f"<p>before</p>{CONTENT[tag]}<p>after</p>")
    assert tag not in names(out)
    assert "X-" not in out
    assert "<p>before</p>" in out and "<p>after</p>" in out
    assert "x.example" not in out


@pytest.mark.parametrize("tag", sorted(CONTENT))
def test_the_name_is_read_without_regard_to_case(tag):
    shout = CONTENT[tag].replace(tag, tag.upper())
    out = sanitize(f"<p>keep</p>{shout}")
    assert tag not in names(out)
    assert "X-" not in out and "<p>keep</p>" in out


def test_an_element_inside_a_kept_element_goes_alone():
    out = sanitize("<table><tr><td>cell<script>x()</script></td></tr></table>")
    assert "<td>cell</td>" in out and "script" not in out


@pytest.mark.parametrize("tag", sorted(ALSO_REMOVED))
def test_the_raw_text_elements_python_versions_disagree_on_go_too(tag):
    out = sanitize(f"<p>before</p><{tag}>X-RAW <script>alert(1)</script> &lt;b&gt;</{tag}><p>after</p>")
    assert tag not in names(out) and "X-RAW" not in out and "alert" not in out
    assert "<p>before</p>" in out
    if tag != "plaintext":       # a browser, and Python 3.14, read everything after it as its text
        assert "<p>after</p>" in out


# ── input ───────────────────────────────────────────────────────────────────

def test_a_task_box_stays():
    out = sanitize('<ul><li><input type="checkbox" checked="" disabled=""/> done</li>'
                   '<li><input type="checkbox" disabled=""/> todo</li></ul>')
    boxes = [a for t, a in tags_of(out) if t == "input"]
    assert len(boxes) == 2
    assert all(a["type"] == "checkbox" for a in boxes)
    assert "checked" in boxes[0] and "checked" not in boxes[1]
    assert " done" in out and " todo" in out


@pytest.mark.parametrize("tag", [
    "<input>", "<input type=text>", '<input type="hidden" name="x" value="y">',
    '<input type="submit">', '<input type="image" src="http://x.example/a.png">',
    '<input type="password">', '<input type="file">', '<input type="radio">',
    "<input type=\"checkbox​\">"])
def test_every_other_input_goes(tag):
    out = sanitize(f"<p>a{tag}b</p>")
    assert "input" not in names(out)
    assert "<p>ab</p>" in out


def test_the_checkbox_test_ignores_case_and_spaces_only():
    assert "input" in names(sanitize('<input type=" CheckBox ">'))


# ── attributes ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("attr", ["onclick", "onerror", "onload", "onmouseover", "ONFOCUS",
                                  "onToggle", "onanimationstart", "onpointerenter", "onx"])
def test_every_attribute_that_starts_with_on_goes(attr):
    out = sanitize(f'<p class="k" {attr}="steal()">text</p><img src="a.png" {attr}=x>')
    for _, a in tags_of(out):
        assert not any(k.lower().startswith("on") for k in a)
    assert 'class="k"' in out and 'src="a.png"' in out and "steal" not in out


def test_srcdoc_and_formaction_go_and_the_element_stays():
    out = sanitize('<div srcdoc="<script>x()</script>" id="k">t</div>'
                   '<input type="checkbox" formaction="http://x.example/">')
    for _, a in tags_of(out):
        assert "srcdoc" not in a and "formaction" not in a
    assert 'id="k"' in out and "input" in names(out)


@pytest.mark.parametrize("attr", ["srcset", "SRCSET", "SrcSet", "ping", "PING"])
def test_srcset_and_ping_go_whatever_they_hold(attr):
    out = sanitize(f'<img src="a.png" alt="k" {attr}="https://x.example/one 1x, https://x.example/two 2x">'
                   f'<a href="https://example.org/" {attr}="https://x.example/track">link</a>')
    for _, a in tags_of(out):
        assert not any(k.lower() in ("srcset", "ping") for k in a)
    assert "x.example" not in out
    assert 'src="a.png"' in out and 'alt="k"' in out and 'href="https://example.org/"' in out
    assert "link" in text_of(out)


def test_srcset_and_ping_go_from_a_relative_value_too_and_are_logged():
    log = []
    out = sanitize('<img src="a.png" srcset="b.png 2x"><a href="#x" ping="/count">t</a>', log=log)
    assert "srcset" not in out and "ping" not in out and 'src="a.png"' in out
    assert log == ["  - srcset removed from <img>", "  - ping removed from <a>"]


def test_an_attribute_that_only_looks_like_srcset_or_ping_stays():
    out = sanitize('<p data-srcset="1" data-ping="2" title="srcset ping">x</p>')
    assert 'data-srcset="1"' in out and 'data-ping="2"' in out and 'title="srcset ping"' in out


def test_the_list_of_dropped_attributes_is_what_the_docstring_says():
    assert DROPPED_ATTRS == {"srcdoc", "formaction", "srcset", "ping"}


def test_an_attribute_that_only_looks_like_on_stays():
    out = sanitize('<p data-on="1" aria-label="on" lang="en">x</p>')
    assert 'data-on="1"' in out and 'aria-label="on"' in out and 'lang="en"' in out


# ── URL attributes ──────────────────────────────────────────────────────────

OK_URLS = ["https://example.com/a?b=1#c", "http://example.com", "HTTPS://EXAMPLE.COM",
           "mailto:ada@example.com", "file:///home/ada/x.md", "relative/path.md",
           "../up.md", "./here.md", "#fragment", "?q=1", "/absolute/path", "//example.com/x",
           "a.md#b"]
BAD_URLS = ["javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)",
            "\tjavascript:alert(1)", "java\nscript:alert(1)", "java\tscript:alert(1)",
            "java&#x09;script:alert(1)", "java&#10;script:alert(1)", "&#106;avascript:alert(1)",
            "javascript&colon;alert(1)", "\x01javascript:alert(1)", "jav\x00ascript:alert(1)",
            "vbscript:msgbox(1)", "data:text/html,<script>alert(1)</script>",
            "data:text/html;base64,PHNjcmlwdD4=", "data:image/svg+xml;base64,PHN2Zz4=",
            "ftp://example.com/x", "blob:https://example.com/x", "tel:+3212345678",
            "about:blank", "x-custom:1", "chrome://settings"]


@pytest.mark.parametrize("attr,tag", [("href", "a"), ("src", "img"), ("action", "div"),
                                      ("poster", "div"), ("background", "table"),
                                      ("xlink:href", "a")])
@pytest.mark.parametrize("url", OK_URLS)
def test_a_safe_address_stays(attr, tag, url):
    out = sanitize(f'<{tag} {attr}="{url}">t</{tag}>')
    [(_, a)] = [x for x in tags_of(out) if x[0] == tag]
    assert a.get(attr) == url


@pytest.mark.parametrize("url", ["  https://example.com/a  ", "\nhttps://example.com/a", "https://example.com/a\t",
                                 "ht\ttps://example.com/a", "https:/\n/example.com/a", "\x01mailto:ada@example.com"])
def test_a_browser_reads_a_padded_or_broken_up_address_as_the_plain_one_and_so_do_we(url):
    out = sanitize(f'<a href="{url}">t</a>')
    [(_, a)] = tags_of(out)
    assert a.get("href") == url


@pytest.mark.parametrize("attr,tag", [("href", "a"), ("src", "img"), ("action", "div"),
                                      ("poster", "div"), ("background", "table"),
                                      ("xlink:href", "a")])
@pytest.mark.parametrize("url", BAD_URLS)
def test_any_other_address_goes_and_the_element_stays(attr, tag, url):
    out = sanitize(f'<{tag} {attr}="{url}" id="k">t</{tag}>')
    [(_, a)] = [x for x in tags_of(out) if x[0] == tag]
    assert attr not in a
    assert a.get("id") == "k"


@pytest.mark.parametrize("mime", ["png", "jpeg", "gif", "webp"])
def test_a_data_image_stays_on_img_src(mime):
    out = sanitize(f'<img src="data:image/{mime};base64,AAAA">')
    assert f"data:image/{mime};base64,AAAA" in out


@pytest.mark.parametrize("tag,attr", [("a", "href"), ("div", "background"), ("div", "poster"),
                                      ("svg", "href"), ("img", "href")])
def test_a_data_image_is_for_img_src_only(tag, attr):
    out = sanitize(f'<{tag} {attr}="data:image/png;base64,AAAA">t</{tag}>')
    [(_, a)] = [x for x in tags_of(out) if x[0] == tag]
    assert attr not in a


def test_the_address_attributes_are_the_six_of_the_spec():
    assert URL_ATTRS == {"href", "src", "action", "poster", "background", "xlink:href"}


def test_svg_animation_cannot_set_a_link():
    out = sanitize('<svg><a><set attributeName="href" to="javascript:alert(1)"/>'
                   '<animate attributeName="xlink:href" values="javascript:alert(1)"/>'
                   '<text>kept</text></a></svg>')
    assert "set" not in names(out) and "animate" not in names(out)
    assert "kept" in out


# ── what stays ──────────────────────────────────────────────────────────────

def test_comments_stay_in_a_page():
    src = ("<!--MDB:0-->\n<p>x</p><!-- sheaf-comment id=c1 by=Ada at=2026-10-14T10:00 "
           "status=open quote=\"x\"\nnote\n-->\n<!-- an ordinary note -->")
    out = sanitize(src)
    assert out == src


def test_comments_go_when_asked_to_for_a_share_copy():
    out = sanitize("<!--MDB:0--><p>x</p><!-- note -->", comments=False)
    assert out == "<p>x</p>"


def test_harmless_markup_stays():
    src = ('<details open=""><summary>s</summary><p>x<sup>1</sup><sub>2</sub><kbd>K</kbd>'
           '<mark>m</mark><br/>y</p></details>'
           '<table><thead><tr><th>h</th></tr></thead><tbody><tr><td>c</td></tr></tbody></table>'
           '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="red"></circle>'
           '<text x="1" y="2">t</text></svg>')
    out = sanitize(src)
    # The same elements with the same attributes (read by a second parser, so the
    # spelling of a void tag or the order of attributes does not matter), the same text.
    assert tags_of(out) == tags_of(src)
    assert text_of(out) == text_of(src)


def test_text_and_entities_come_out_as_they_went_in():
    src = "<p>1 &lt; 2 &amp; 3 &gt; 0, &quot;quoted&quot;, café, —</p>"
    assert sanitize(src) == src.replace("&quot;", '"')


def test_a_whole_pandoc_page_survives_with_its_task_boxes_and_tables():
    from helpers import pandoc
    src = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"],
                 "# T\n\n- [x] a\n- [ ] b\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n`c` and *d*.\n")
    out = sanitize(src)
    assert tags_of(out) == tags_of(src)
    assert text_of(out) == text_of(src)
    assert out.count('type="checkbox"') == 2


# ── what has no honest round trip ───────────────────────────────────────────

def test_cdata_declarations_and_processing_instructions_go():
    for src in ('<![CDATA[><script>alert(1)</script>]]>', "<?php echo 1 ?>", "<!DOCTYPE html>",
                "<!ELEMENT x>"):
        out = sanitize(f"<p>a</p>{src}<p>b</p>")
        assert "<script" not in out and "CDATA" not in out and "php" not in out
        assert "<p>a</p>" in out and "<p>b</p>" in out


def test_a_comment_a_browser_would_end_early_goes():
    out = sanitize("<p>a</p><!-- x --!> <img src=y onerror=alert(1)> --><p>b</p>")
    for _, a in tags_of(out):
        assert "onerror" not in a
    assert "<p>a</p>" in out and "<p>b</p>" in out


@pytest.mark.parametrize("c", ["<!-->", "<!--->"])
def test_an_empty_comment_opener_is_written_out_as_a_whole_comment(c):
    out = sanitize(f"<p>a</p>{c}<p>b</p>")
    assert "<p>a</p>" in out and "<p>b</p>" in out
    assert c not in out and out.count("<!--") == out.count("-->") == 1


def test_an_empty_comment_opener_ends_at_its_own_bracket_whatever_the_pythons_parser_does():
    """A browser ends `<!-->` at its `>` (an empty comment) and reads what follows as markup.
    Python's parser read it as text before 3.11.14, 3.12.12 and 3.13.6, and from those on it
    looks for a later `-->` first and swallows everything up to it."""
    out = sanitize('<p>a</p><!--><img src="x" onerror="y"><p>b</p>-->')
    assert [t for t, _ in tags_of(out)] == ["p", "img", "p"]
    assert all("onerror" not in a for _, a in tags_of(out))
    assert "<p>a</p>" in out and "<p>b</p>" in out
    assert out.count("<!--") == 1 and "<!-->" not in out


@pytest.mark.parametrize("fragment, expected", [
    ('<p title="<!-->">x</p>', '<p title="&lt;!--&gt;">x</p>'),
    ("<p title='<!--->'>x</p>", '<p title="&lt;!---&gt;">x</p>'),
    ("<p>&lt;!--&gt;</p>", "<p>&lt;!--&gt;</p>"),
])
def test_what_only_looks_like_an_empty_comment_opener_is_left_as_it_was(fragment, expected):
    assert sanitize(fragment) == expected


def test_a_comment_that_opens_another_goes():
    out = sanitize("<p>a</p><!-- a <!-- b --><p>b</p>")
    assert out == "<p>a</p><p>b</p>"


# ── properties ──────────────────────────────────────────────────────────────

HOSTILE = [
    "<scr<script>ipt>alert(1)</scr</script>ipt>", "<img/src=x/onerror=alert(1)>",
    "<svg><script>alert(1)</script></svg>", "<svg onload=alert(1)>",
    "<a href=\"jav&#x61;script:alert(1)\">x</a>", "<math href=javascript:alert(1)>x</math>",
    "<p title=\"</p><script>alert(1)</script>\">x</p>", "<a href=`javascript:1`>x</a>",
    "<div style='x' onmouseover=\"a()\"/>", "<![CDATA[x]]><script>y()</script>",
    "<img src=x onerror=alert(1) src=y>", "<IMG SRC=JaVaScRiPt:alert(1)>",
    "<body onload=alert(1)>", "<video><source onerror=alert(1)></video>",
    "<input type=checkbox onfocus=alert(1) autofocus>", "<details open ontoggle=alert(1)>",
    "<svg><a xlink:href=javascript:alert(1)><text>x</text></a></svg>",
    "<svg><animate onbegin=alert(1) attributeName=x dur=1s>", "<p onclick=a() onclick=b()>x",
    "<iframe srcdoc='<script>1</script>'>", "<object data=javascript:1>", "<<script>script>x</script>",
    "<a href=\"&#14;javascript:alert(1)\">x</a>", "<noscript><img src=x onerror=1></noscript>",
    "<xmp><script>alert(1)</script></xmp>", "<listing><img src=x onerror=1></listing>",
    "<style>@import 'http://x.example/'</style>", "<form><button formaction=javascript:1>",
    "<img src=a.png srcset='https://x.example/a 1x'>", "<a href=# ping='https://x.example/p'>x</a>",
]


def forbidden_left(out: str) -> list[str]:
    left = []
    for tag, attrs in tags_of(out):
        if tag in REMOVE:
            left.append(f"<{tag}>")
        if tag == "input" and attrs.get("type", "").strip().lower() != "checkbox":
            left.append("<input>")
        for k, v in attrs.items():
            if k.startswith("on") or k in DROPPED_ATTRS:
                left.append(k)
            if k in URL_ATTRS and v and v.strip().lower().startswith(
                    ("javascript:", "vbscript:", "data:text", "data:image/svg")):
                left.append(f"{k}={v}")
    return left


@pytest.mark.parametrize("src", HOSTILE)
def test_nothing_forbidden_is_left_and_a_second_pass_changes_nothing(src):
    out = sanitize(f"<p>ok</p>{src}<p>end</p>")
    assert forbidden_left(out) == []
    assert sanitize(out) == out


def test_random_mixtures_of_hostile_pieces_never_leave_anything_forbidden():
    rng = random.Random(20261014)
    pieces = HOSTILE + ["<p>", "</p>", "text &amp; more", "<!-- c -->", "<b>", "</b>", "<td>", "<br>",
                        "<a href=ok.md>", "</a>", "<img src=a.png>", "<!--", "-->", "--!>", "<", ">"]
    for _ in range(400):
        src = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
        for comments in (True, False):
            out = sanitize(src, comments=comments)
            assert forbidden_left(out) == [], (src, out)
            assert sanitize(out, comments=comments) == out, (src, out)
            if not comments:
                assert "<!--" not in out, (src, out)


def test_the_log_names_each_removal():
    log = []
    sanitize('<script>x</script><a href="javascript:1" onclick="y()">z</a>', log=log)
    assert any("<script>" in line for line in log)
    assert any("onclick" in line for line in log)
    assert any("href" in line for line in log)
    assert all(line.startswith("  - ") for line in log)


def test_the_result_is_taken_through_again_until_nothing_changes(monkeypatch):
    from sheafmd import sanitize as S
    calls = []

    def fake(fragment, comments, log, mount=False):
        calls.append(fragment)
        return fragment[:-1] if fragment.endswith("x") else fragment
    monkeypatch.setattr(S, "_pass", fake)
    assert S.sanitize("abxxx") == "ab"
    assert calls == ["abxxx", "abxx", "abx"]          # one pass each, and no more than MAX_PASSES
    calls.clear()
    assert S.sanitize("stable") == "stable" and len(calls) == 1


def test_a_tree_nested_hundreds_of_levels_deep_is_cleaned_like_a_shallow_one():
    # bs4 wrote the tree out with a loop that compares tags, one level of the stack for
    # each level of nesting, so this raised RecursionError at 248 levels on 3.11 and 496 on 3.12.
    n = 700
    hostile = '<p>KEEP<script>alert(1)</script><img src="javascript:x" onerror="y"></p>'
    log = []
    out = sanitize("<blockquote>\n" * n + hostile + "</blockquote>\n" * n, log=log)
    assert out.count("<blockquote>") == n and "<p>KEEP<img/></p>" in out
    assert "script" not in out and "onerror" not in out and "javascript:" not in out
    assert len(log) == 3
