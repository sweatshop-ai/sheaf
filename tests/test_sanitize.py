"""The raw-HTML sanitiser (SPEC 9.5, tests of SPEC 18 Security): each item removed,
task boxes and comments kept.

Every removal test also asserts what must SURVIVE next to it, so a sanitiser that
empties the document cannot pass."""
import html
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


def test_the_checkbox_test_ignores_case_only():
    assert "input" in names(sanitize('<input type="CheckBox">'))


@pytest.mark.parametrize("mount", [False, True])
@pytest.mark.parametrize("kind", [" checkbox", "checkbox ", " CheckBox ", "\tcheckbox", "checkbox\n", "\u00a0checkbox", "chec\u212abox"])
def test_a_type_that_is_not_exactly_checkbox_is_no_checkbox(kind, mount):
    """A browser matches the type exactly, ASCII case aside: `" checkbox"` (a space) is a text field, and so is `"checKbox"` with a Kelvin sign, which `str.lower()` would fold to an ASCII k."""
    out = sanitize(f'<p>a<input type="{kind}">b</p>', mount=mount)
    assert "input" not in names(out)
    assert "<p>ab</p>" in out


@pytest.mark.parametrize("mount", [False, True])
@pytest.mark.parametrize("value", ["true", "plaintext-only", "", "TRUE", "false"])
def test_the_document_has_no_contenteditable_of_its_own(value, mount):
    """The page owns editability (setEditing): a surface the document makes editable is outside what the page guards."""
    out = sanitize(f'<p class="k">a<span contenteditable="{value}">b</span><em contenteditable>c</em></p>', mount=mount)
    for _, a in tags_of(out):
        assert "contenteditable" not in a
    assert "<span>b</span>" in out and "<em>c</em>" in out


@pytest.mark.parametrize("mount", [False, True])
@pytest.mark.parametrize("spelling", ["CONTENTEDITABLE", "ContentEditable", 'contenteditable="true" contenteditable="false"',
                                      'contenteditable="false" contenteditable="true"'])
def test_contenteditable_goes_in_any_letter_case_and_when_repeated(spelling, mount):
    """The upper-case and repeated spellings pass on main without the contenteditable rule's help too: html.parser lowercases
    attribute names and keeps one of two duplicates before the sanitiser sees them. They pin that behaviour; they do not test the rule."""
    out = sanitize(f"<p>a<span {spelling}>b</span></p>", mount=mount)
    assert "contenteditable" not in out.lower()
    assert "<span>b</span>" in out


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
    assert DROPPED_ATTRS == {"srcdoc", "formaction", "srcset", "ping", "contenteditable"}


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


@pytest.mark.parametrize("decl", ["-webkit-user-modify: read-write", "-WEBKIT-USER-MODIFY:read-write-plaintext-only",
                                  "-moz-user-modify: read-write", "user-modify: read-write",
                                  "-webkit-user-\\6d odify: read-write", "/*;*/-webkit-user-modify: read-write",
                                  "/*:*/-webkit-user-modify: read-write", "/* a:b */ -webkit-user-modify:read-write",
                                  "/*:*/-webkit-user-\\6d odify: read-write"])
def test_a_style_attribute_cannot_make_text_editable(decl):
    """CSS makes a span editable in Chromium and WebKit (tests/page/test_user_modify.py), and the page's
    closest('[contenteditable="true"]') does not see it. The other declarations of the attribute stay."""
    out = sanitize(f'<p>a<span style="color: red; {decl}; width: 3px">b</span></p>')
    assert "modify" not in out.lower() and "\\" not in out
    assert "color: red" in out and "width: 3px" in out


@pytest.mark.parametrize("style, want", [
    ('content: "a;\\201C"; color: red', " color: red"),
    ("content: 'a;\\201C'; color: red", " color: red"),
    ('content: "a;b"; color: red', 'content: "a;b"; color: red'),
    ('content: "a;-webkit-user-modify: read-write"; color: red', " color: red"),
    ('content: "a\\";-webkit-user-modify: read-write"; color: red', " color: red"),
    ("/* ; \" */ color: red; -webkit-user-modify: read-write", "/* ; \" */ color: red"),
    ('content: "a\n; -webkit-user-modify: read-write; color: red', 'content: "a\n; color: red'),
    ('content: "a;\\201C; -webkit-user-modify: read-write; width: 3px', None),
    ("background: url(data:image/png;base64,AAA); -webkit-user-modify: read-write", "background: url(data:image/png;base64,AAA)"),
    ("background: url(data:image/png;base64,AAA); color: red", "background: url(data:image/png;base64,AAA); color: red"),
    ("a: url(x;-webkit-user-modify: read-write); color: red", " color: red"),
    ("a: [x;-webkit-user-modify: read-write]; color: red", " color: red"),
    ("a: {x;-webkit-user-modify: read-write}; color: red", " color: red"),
    ("a: f(g(x;y);z); -webkit-user-modify: read-write; color: red", "a: f(g(x;y);z); color: red"),
    ("a: f(x; color: red; -webkit-user-modify: read-write", None),
    ("a: b); -webkit-user-modify: read-write; color: red", "a: b); color: red"),
    ('content: "("; -webkit-user-modify: read-write; color: red', 'content: "("; color: red'),
    ("/*(*/ -webkit-user-modify: read-write; color: red", " color: red"),
])
def test_the_style_filter_splits_on_the_semicolons_the_browser_splits_on(style, want):
    """A `;` inside a CSS string or a comment does not end a declaration: a declaration dropped whole leaves the next one
    intact, never a truncated rest. A string a newline ends is over, as in a browser. `want` None: the whole text is one
    declaration for the browser, and nothing is kept.
    Whatever the split, nothing with user-modify or a backslash comes out."""
    out = sanitize(f'<p><span style="{html.escape(style)}">b</span></p>')
    assert "user-modify" not in out.lower() and "\\" not in out
    span = next(a for t, a in tags_of(out) if t == "span")
    assert span.get("style") == want


def test_a_declaration_with_a_backslash_goes_and_its_neighbours_stay():
    """The backslash rule is wider than it needs to be (an escape in `content` is harmless) and drops ordinary
    declarations too; this pins that, so a narrowing is a decision and not an accident."""
    out = sanitize('<span style=\'color: red; content:"\\201C"; width: 3px\'>b</span>')
    assert "color: red" in out and "width: 3px" in out
    assert "content" not in out and "\\" not in out


def test_simple_mode_logs_a_trimmed_style_like_mount_mode():
    log = []
    sanitize('<span style="color: red; -webkit-user-modify: read-write">x</span>', log=log)
    assert log == ["  - style trimmed on <span>"]
    log = []
    sanitize('<span style="color: red">x</span>', log=log)
    assert log == []


@pytest.mark.parametrize("style", [
    "-webkit-user-modify:read-write",
    "-webkit-user-modify:read-write;",
    ";;-webkit-user-modify:read-write",
    "/* c */; -webkit-user-modify:read-write",
    "/* a */ ;; /* -webkit-user-modify:read-write */",
    "/* a */ -webkit-user-modify:read-write; /* b */",
    "-webkit-user-modify:read-write; /* unterminated",
    "-WEBKIT-USER-MODIFY:read-write ;\t\n; ",
    "-webkit-user-\\6d odify:read-write;;",
    "-moz-user-modify:read-write; -webkit-user-modify:read-write",
])
def test_a_style_the_filter_empties_is_removed(style):
    """No declaration left, only separators, comments and white space: the attribute goes, not a stub of it."""
    log = []
    out = sanitize(f'<span style="{html.escape(style)}">x</span>', log=log)
    assert out == "<span>x</span>"
    assert "  - style trimmed on <span>" in log


@pytest.mark.parametrize("style, want", [
    ("color: red; -webkit-user-modify:read-write; ;;", "color: red; ;;"),
    ('content: ";"; -webkit-user-modify:read-write', 'content: ";"'),
    ('content: "/*"; -webkit-user-modify:read-write', 'content: "/*"'),
    ("-webkit-user-modify:read-write; width: 3px", " width: 3px"),
    ("-webkit-user-modify:read-write; /* c */ width: 3px", " /* c */ width: 3px"),
])
def test_a_style_with_a_declaration_left_keeps_the_attribute(style, want):
    out = sanitize(f'<span style="{html.escape(style)}">x</span>')
    assert next(a for t, a in tags_of(out) if t == "span").get("style") == want


def test_a_style_only_a_comment_or_separators_that_the_filter_did_not_touch_is_left_alone():
    """Only what the filter trimmed is judged: a style it did not change comes out as it came in."""
    out = sanitize('<span style=";; /* c */">x</span>')
    assert next(a for t, a in tags_of(out) if t == "span").get("style") == ";; /* c */"


def test_mount_mode_removes_a_style_the_allow_list_empties():
    """Not part of the simple-mode filter: `_mount_attrs` did this before the filter was string-aware; kept as a guard."""
    log = []
    out = sanitize('<span style="-webkit-user-modify:read-write">x</span>', log=log, mount=True)
    assert out == "<span>x</span>"
    assert "  - style trimmed on <span>" in log


def test_no_split_of_a_style_lets_user_modify_or_a_backslash_through():
    """Bypass neighbours of the string- and comment-aware split: quotes, comments, escapes and newlines in every order
    around a declaration that makes text editable. The split may differ from a browser's; the output may not carry the name."""
    pieces = ['"', "'", "/*", "*/", ";", "\\", "\n", ":", " ", "(", ")", "[", "]", "{", "}", "color: red", "-webkit-user-modify: read-write", "user-modify",
              "-moz-user-\\6d odify:read-write", "a", "url(", "URL( ", "url(/*", "url(it's", "@", "#", "\\75 ", "@url(", "#url(", "\\3a "]
    rng = random.Random(96)
    for _ in range(3000):
        style = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
        out = sanitize(f'<span style="{html.escape(style)}">x</span>')
        assert "user-modify" not in out.lower() and "\\" not in out, style
        assert sanitize(out) == out, style


@pytest.mark.parametrize("style, want", [
    ("color: red; -webkit-user-modify: read-write;", "color: red;"),
    ("color: red;", "color: red;"),
    ('content: "/*"; color: red; -webkit-user-modify: read-write', 'content: "/*"; color: red'),
    ('content: "*/"; color: red; -webkit-user-modify: read-write', 'content: "*/"; color: red'),
])
def test_the_edges_of_the_split_a_trailing_semicolon_and_comment_marks_inside_a_string(style, want):
    out = sanitize(f'<span style="{html.escape(style)}">x</span>')
    assert next(a for t, a in tags_of(out) if t == "span").get("style") == want


@pytest.mark.parametrize("style, want", [
    ("background:url(/*a.png);-webkit-user-modify:x;color:red", "background:url(/*a.png);color:red"),
    ("background:url(it's.png);-webkit-user-modify:x;color:red", "background:url(it's.png);color:red"),
    ('background:url(a"b.png);-webkit-user-modify:x;color:red', 'background:url(a"b.png);color:red'),
    ("background:URL(/*a.png);-webkit-user-modify:x;color:red", "background:URL(/*a.png);color:red"),
    ("background:url( /*a.png );-webkit-user-modify:x;color:red", "background:url( /*a.png );color:red"),
    ("background:url(\n/*a.png);-webkit-user-modify:x;color:red", "background:url(\n/*a.png);color:red"),
    ("a:image-set(url(/*a.png) 1x);-webkit-user-modify:x;color:red", "a:image-set(url(/*a.png) 1x);color:red"),
    ("a:url(/*a.png);b:url(it's.png);-webkit-user-modify:x;color:red", "a:url(/*a.png);b:url(it's.png);color:red"),
    ("a:url(x;-webkit-user-modify:x);color:red", "color:red"),
    ("-webkit-user-modify:x;a:url(/*b);color:red", "a:url(/*b);color:red"),
    ("a:url(/*b", "a:url(/*b"),
])
def test_an_unquoted_url_is_one_token_up_to_its_closing_bracket(style, want):
    """CSS reads `url(` followed by no quote as a single token that ends at the first `)`: a `/*` or a quote inside it
    starts no comment and no string, so the declarations after it stay, as in a browser."""
    out = sanitize(f'<p><span style="{html.escape(style)}">b</span></p>')
    assert "user-modify" not in out.lower()
    assert next(a for t, a in tags_of(out) if t == "span").get("style") == want


@pytest.mark.parametrize("style, want", [
    ("a:xurl(/*b*/);-webkit-user-modify:x;color:red", "a:xurl(/*b*/);color:red"),
    ("a:xurl(/*b);-webkit-user-modify:x;color:red", None),
    ("a:x-url(it's);-webkit-user-modify:x;color:red", None),
    ('a:url("/*b");-webkit-user-modify:x;color:red', 'a:url("/*b");color:red'),
    ("a:url( 'it;s');-webkit-user-modify:x;color:red", "a:url( 'it;s');color:red"),
    ('a:url( "b)c.png");color:red;-webkit-user-modify:x', 'a:url( "b)c.png");color:red'),
    ("a:url(\n'b)c.png');color:red;-webkit-user-modify:x", "a:url(\n'b)c.png');color:red"),
    ('content:"url(/*";-webkit-user-modify:x;color:red', 'content:"url(/*";color:red'),
    ("/*url(*/-webkit-user-modify:x;color:red", "color:red"),
    ("a:url(b\\);c);color:red", "color:red"),
    ("a:€url(/*b*/);-webkit-user-modify:x;color:red", "a:€url(/*b*/);color:red"),
    ("a:€url(/*b);-webkit-user-modify:x;color:red", None),
])
def test_only_a_plain_unquoted_url_is_read_as_a_token(style, want):
    """A function whose name only ends in `url`, a `url(` with a string, one inside a string or a comment keeps the
    string and comment rules. `want` None: the text is one declaration for the browser, and no style is left."""
    out = sanitize(f'<p><span style="{html.escape(style)}">b</span></p>')
    assert "user-modify" not in out.lower()
    assert next(a for t, a in tags_of(out) if t == "span").get("style") == want


# --- ticket 110: the split is checked against a reference that follows the CSS Syntax 3 tokenizer --------------------------------

def _css_reference_split(s: str) -> list[str]:
    """`s` cut at the `;` that end a declaration, by the CSS Syntax 3 tokenizer (3.3 to 4.3) and its block nesting: a written
    out second implementation that shares no code with `_declarations`. A `(`, `[`, `{` and a function open a block that only
    its own closer ends; a closer that does not match the innermost block is a token of its own; a block left open runs to the end."""
    n, i, cuts, blocks = len(s), 0, [], []
    ws, hexd = " \t\n\r\f", "0123456789abcdefABCDEF"

    def at(k):
        return s[k] if k < n else ""

    def valid_escape(k):
        return at(k) == "\\" and at(k + 1) != "\n"

    def name_char(c):
        return bool(c) and (c.isascii() and (c.isalnum() or c in "_-") or ord(c) >= 0x80)

    def name_start(c):
        return bool(c) and (c.isascii() and (c.isalpha() or c == "_") or ord(c) >= 0x80)

    def start_ident(k):
        c = at(k)
        if c == "-":
            return name_start(at(k + 1)) or at(k + 1) == "-" or valid_escape(k + 1)
        return name_start(c) or valid_escape(k)

    def start_number(k):
        c = at(k)
        if c in "+-":
            return at(k + 1).isdigit() or (at(k + 1) == "." and at(k + 2).isdigit())
        return c.isdigit() if c != "." else at(k + 1).isdigit()

    def escape(k):
        """(text, next index) of the escape that starts after the backslash at k - 1."""
        c = at(k)
        if not c:
            return "\ufffd", k
        if c in hexd:
            j = k
            while j < k + 6 and at(j) and at(j) in hexd:
                j += 1
            v = int(s[k:j], 16)
            if at(j) == "\r" and at(j + 1) == "\n":
                j += 2
            elif at(j) and at(j) in ws:
                j += 1
            return ("\ufffd" if v == 0 or v > 0x10FFFF or 0xD800 <= v <= 0xDFFF else chr(v)), j
        return c, k + 1

    def name(k):
        out = []
        while True:
            if name_char(at(k)):
                out.append(at(k))
                k += 1
            elif valid_escape(k):
                t, k = escape(k + 1)
                out.append(t)
            else:
                return "".join(out), k

    def bad_url(k):
        while at(k) and at(k) != ")":
            k = escape(k + 1)[1] if valid_escape(k) else k + 1
        return k + 1 if at(k) == ")" else k

    def url(k):
        while at(k) and at(k) in ws:
            k += 1
        while True:
            c = at(k)
            if c in ("", ")"):
                return k + 1 if c else k
            if c in ws:
                while at(k) and at(k) in ws:
                    k += 1
                return k + 1 if at(k) == ")" else (k if not at(k) else bad_url(k))
            if c in "\"'(" or (c.isascii() and ord(c) < 0x20 and c not in "\t\n\r\f") or ord(c) == 0x7F:
                return bad_url(k)
            if c == "\\":
                if not valid_escape(k):
                    return bad_url(k)
                k = escape(k + 1)[1]
            else:
                k += 1

    while i < n:
        c = s[i]
        if c in ws:
            while at(i) and at(i) in ws:
                i += 1
        elif s.startswith("/*", i):
            end = s.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "\"'":
            i += 1
            while i < n and s[i] != c and s[i] not in "\n":
                if s[i] == "\\":
                    i += 2 if i + 1 < n else 1
                else:
                    i += 1
            if at(i) == c:
                i += 1
        elif c == "#":
            i = name(i + 1)[1] if name_char(at(i + 1)) or valid_escape(i + 1) else i + 1
        elif c in "([{":
            blocks.append({"(": ")", "[": "]", "{": "}"}[c])
            i += 1
        elif c in ")]}":
            if blocks and blocks[-1] == c:
                blocks.pop()
            i += 1
        elif c == ";":
            if not blocks:
                cuts.append(i)
            i += 1
        elif c == "@":
            i = name(i + 1)[1] if start_ident(i + 1) else i + 1
        elif c in "+-." and start_number(i) or c.isdigit():
            j = i + 1 if c in "+-" else i
            while at(j).isdigit():
                j += 1
            if at(j) == "." and at(j + 1).isdigit():
                j += 1
                while at(j).isdigit():
                    j += 1
            if at(j) in ("e", "E") and (at(j + 1).isdigit() or at(j + 1) in ("+", "-") and at(j + 2).isdigit()):
                j += 2
                while at(j).isdigit():
                    j += 1
            i = name(j)[1] if start_ident(j) else j
        elif c == "-" and s.startswith("-->", i):
            i += 3
        elif c == "<" and s.startswith("<!--", i):
            i += 4
        elif start_ident(i):
            word, j = name(i)
            if at(j) == "(":
                j += 1
                if word.lower() == "url":
                    k = j
                    while at(k) in ws and at(k) and at(k + 1) in ws and at(k + 1):
                        k += 1
                    if at(k) in ("\"", "'") or (at(k) in ws and at(k) and at(k + 1) in ("\"", "'")):
                        blocks.append(")")
                        i = j
                    else:
                        i = url(j)
                else:
                    blocks.append(")")
                    i = j
            else:
                i = j
        else:
            i += 1
    parts, start = [], 0
    for k in cuts:
        parts.append(s[start:k])
        start = k + 1
    parts.append(s[start:])
    return parts


SPLIT_CASES = [
    # (style, the declarations a browser sees)
    ("a:url(b;c);d:e", ["a:url(b;c)", "d:e"]),
    ("a:url(/*b)*/;c:d", ["a:url(/*b)*/", "c:d"]),          # a url token ends at its first `)`: the comment never starts
    ("a:@url(/*b)*/;c:d", ["a:@url(/*b)*/;c:d"]),               # C1: an at-keyword, then a `(` block: `/*b)*/` is a comment, the block is open
    ("a:#url(/*b)*/;c:d", ["a:#url(/*b)*/;c:d"]),               # C1: a hash, the same
    ("a:#url(it's;b);c:d", ["a:#url(it's;b);c:d"]),            # C1: the quote opens a string in the block
    ("a:\\75 rl(/*b)*/;c:d", ["a:\\75 rl(/*b)*/", "c:d"]),  # C2: the escape spells `u`: `\75 rl(` is a url token
    ("a:\\75 url(/*b)*/;c:d", ["a:\\75 url(/*b)*/;c:d"]),      # C2: the escape is part of the name `uurl`: a function, a comment
    ("a:b\\:url(/*b)*/;c:d", ["a:b\\:url(/*b)*/;c:d"]),        # C2: the same, with an escaped colon
    ("a:u\\72 l(/*b)*/;c:d", ["a:u\\72 l(/*b)*/", "c:d"]),  # an escape inside the name
    ("a:(];b);c:d", ["a:(];b)", "c:d"]),                        # C3: `]` does not close a `(` block
    ("a:[);b];c:d", ["a:[);b]", "c:d"]),
    ("a:{(};b)};c:d", ["a:{(};b)}", "c:d"]),
    ("a:(b;c)];d:e", ["a:(b;c)]", "d:e"]),                      # C3: a closer with no opener is ignored
    ("a:url(b;c;d", ["a:url(b;c;d"]),
    ("a:b(;c)d;e:f", ["a:b(;c)d", "e:f"]),
    ("a:1url(/*b)*/;c:d", ["a:1url(/*b)*/;c:d"]),
    ("a:-url(/*b)*/;c:d", ["a:-url(/*b)*/;c:d"]),
    ("a: url(/*b)*/;c:d", ["a: url(/*b)*/", "c:d"]),
    ("a:.url(/*b)*/;c:d", ["a:.url(/*b)*/", "c:d"]),
]


@pytest.mark.parametrize("style, want", SPLIT_CASES)
def test_the_reference_splitter_reads_the_cases_as_a_browser_does(style, want):
    """Guards the reference of the next test: a reference that is wrong would let a wrong split pass."""
    assert _css_reference_split(style) == want


@pytest.mark.parametrize("style, want", SPLIT_CASES)
def test_a_style_is_cut_where_the_css_tokenizer_cuts_it(style, want):
    from sheafmd.sanitize import _declarations
    assert _declarations(style) == want


def test_the_split_of_a_style_equals_the_reference_split():
    """Whatever the split, the name is searched in each piece whole (the test above this one); this one sees a split that
    drifts from a browser's, which would keep too little or too much without ever hiding the name."""
    from sheafmd.sanitize import _declarations
    pieces = ['"', "'", "/*", "*/", ";", "\\", "\n", ":", " ", "(", ")", "[", "]", "{", "}", "@", "#", "-", ".", "1", "a", "u", "url(", "URL(",
              "rl(", "\\75 ", "\\75", "\\3a ", "\\:", "url( ", "e", "color: red", "-webkit-user-modify: read-write", "€", "\r\n"]
    rng = random.Random(110)
    for _ in range(20000):
        style = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
        assert _declarations(style) == _css_reference_split(style), repr(style)
