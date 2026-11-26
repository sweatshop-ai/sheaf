"""The inline button, end to end (block editor v1, ticket 06): `[[Label](url)]{.button size="m" variant="primary"}`.

It is inline content, so it sits in a paragraph, a table cell or a callout. Declared once (size S/M/L, variant
primary/secondary/outline, a link of http, https, mailto or a relative address and nothing else), checked on write,
stripped on render in both sanitiser layers (`sanitize.py` here, `page/mount.js` in tests/page/test_mount_button.py, from
the same CASES), and laid out by the base stylesheet and Theme properties."""
import re

import pytest

import sheafmd
from sheafmd import adapter as rda
from sheafmd.blocks import declarations as dec
from sheafmd.blocks import read_tree, write_back
from sheafmd.document import DocumentService
from sheafmd.sanitize import sanitize

BUTTON = '[[Book a call](https://example.org/call)]{.button size="m" variant="primary"}'
PWN = "window.__pwned=1"


# ── the declaration ──────────────────────────────────────────────────────────

def test_the_button_is_declared_inline_with_sizes_variants_and_no_children():
    b = dec.INLINE["button"]
    assert b.tag == "span" and b.children == ()
    by = {a.name: a for a in b.attrs}
    assert set(by) == {"size", "variant"}
    assert by["size"].values == ("s", "m", "l") and by["size"].default == "m"
    assert by["variant"].values == ("primary", "secondary", "outline") and by["variant"].default == "primary"


def test_the_allow_list_names_the_attributes_as_pandoc_writes_them():
    # pandoc writes `size` bare (it is an HTML attribute) and every other attribute as data-<name>
    assert dec.allow_list()["button"] == {"tag": "span", "attrs": {"size": ["s", "m", "l"],
                                                                  "data-variant": ["primary", "secondary", "outline"]}}
    assert dec.check_attrs("button", {"size": "l", "variant": "outline"}) is None
    assert "size" in dec.check_attrs("button", {"size": "xl"})
    assert "onclick" in dec.check_attrs("button", {"onclick": "x"})


@pytest.mark.parametrize("url,ok", [
    ("https://example.org/a?b=1#c", True), ("http://example.org", True), ("mailto:a@example.org", True),
    ("/pricing", True), ("pricing.html", True), ("../up", True), ("#top", True), ("?q=1", True),
    ("javascript:alert(1)", False), ("JaVaScRiPt:alert(1)", False), ("java\nscript:alert(1)", False),
    (" javascript:alert(1)", False), ("file:///etc/passwd", False), ("FILE:///etc/passwd", False),
    ("data:text/html,<script>1</script>", False), ("vbscript:x", False), ("tel:+3212345", False),
    ("ftp://example.org", False), ("https:\\\\example.org", False), ("blob:https://example.org/x", False),
])
def test_the_link_rule_allows_http_https_mailto_and_relative_only(url, ok):
    assert dec.link_ok(url) is ok


# ── reading and writing ──────────────────────────────────────────────────────

DOC = ("# T\n\nText, then a button: " + BUTTON + " and more.\n\n"
       '| plan | action |\n|------|--------|\n| Pro | [[Buy](/buy)]{.button size="s" variant="outline"} |\n\n'
       '::: {#c1 .callout tone="info"}\nSee ' + '[[Docs](mailto:a@example.org)]{.button size="l" variant="secondary"}' + '.\n:::\n')


def test_a_document_with_buttons_in_a_paragraph_a_table_cell_and_a_callout_round_trips_byte_for_byte():
    tree = read_tree(DOC)
    assert write_back(tree, tree) == DOC
    assert [b.type for b in tree.blocks] == ["heading", "paragraph", "table", "callout"]
    assert not any(b.type == "stub" for b in tree.blocks)


@pytest.fixture
def doc(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(DOC, encoding="utf-8")
    return path, DocumentService(rda.MarkdownFileAdapter(path))


def _save(svc, markdown, held=None):
    _, base = svc.adapter.read()
    return svc.save(markdown, held, base, "page-1")


def test_an_edit_next_to_the_buttons_leaves_their_bytes_alone(doc):
    path, svc = doc
    out = _save(svc, DOC.replace("and more.", "and a lot more."))
    assert out["outcome"] == "written"
    assert path.read_text(encoding="utf-8") == DOC.replace("and more.", "and a lot more.")
    assert BUTTON in path.read_text(encoding="utf-8")


def test_a_label_and_a_link_can_be_edited(doc):
    path, svc = doc
    new = DOC.replace("Book a call", "Call us").replace("https://example.org/call", "/contact")
    assert _save(svc, new)["outcome"] == "written"
    assert '[[Call us](/contact)]{.button size="m" variant="primary"}' in path.read_text(encoding="utf-8")


BAD = {
    "javascript": '[[Go](javascript:alert(1))]{.button size="m" variant="primary"}',
    "javascript upper": '[[Go](JAVASCRIPT:alert(1))]{.button size="m" variant="primary"}',
    "file": '[[Go](file:///etc/passwd)]{.button size="m" variant="primary"}',
    "data": '[[Go](data:text/html,x)]{.button size="m" variant="primary"}',
    "onclick": '[[Go](/x)]{.button size="m" variant="primary" onclick="x"}',
    "style": '[[Go](/x)]{.button size="m" variant="primary" style="color:red"}',
    "target on the span": '[[Go](/x)]{.button size="m" variant="primary" target="_blank"}',
    "target on the link": '[[Go](/x){target="_blank"}]{.button size="m" variant="primary"}',
    "size": '[[Go](/x)]{.button size="xl" variant="primary"}',
    "variant": '[[Go](/x)]{.button size="m" variant="neon"}',
    "an id": '[[Go](/x)]{#b1 .button size="m" variant="primary"}',
    "a second class": '[[Go](/x)]{.button .wide size="m" variant="primary"}',
    "no link": '[Go]{.button size="m" variant="primary"}',
    "two links": '[[Go](/x) and [there](/y)]{.button size="m" variant="primary"}',
    "text with the link": '[Click [Go](/x)]{.button size="m" variant="primary"}',
    "an image inside": '[[![a](/i.png)](/x)]{.button size="m" variant="primary"}',
}


@pytest.mark.parametrize("name", sorted(BAD))
def test_an_unsafe_or_undeclared_button_is_refused_whole_with_the_block_and_the_file_is_unchanged(doc, name):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    out = _save(svc, before.replace("and more.", "and more " + BAD[name] + "."))
    assert out["outcome"] == "refused", out
    assert out["block"] == read_tree(before.replace("and more.", "and more " + BAD[name] + ".")).blocks[1].id
    assert "button" in out["reason"]
    assert path.read_text(encoding="utf-8") == before


def test_a_bad_button_in_a_table_cell_and_in_a_callout_is_refused_too(doc):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    cell = _save(svc, before.replace("[[Buy](/buy)]", "[[Buy](javascript:x)]"))
    assert cell["outcome"] == "refused" and "javascript" in cell["reason"]
    inner = _save(svc, before.replace("[[Docs](mailto:a@example.org)]", "[[Docs](file:///x)]"))
    assert inner["outcome"] == "refused" and inner["block"] == "c1" and "file" in inner["reason"]
    assert path.read_text(encoding="utf-8") == before


def test_a_new_paragraph_with_a_bad_button_is_refused(doc):
    path, svc = doc
    before = path.read_text(encoding="utf-8")
    out = _save(svc, before + "\n" + BAD["javascript"] + "\n")
    assert out["outcome"] == "refused" and "javascript" in out["reason"]
    assert path.read_text(encoding="utf-8") == before


def test_a_bad_button_already_in_the_file_does_not_refuse_a_save_that_leaves_it_alone(tmp_path):
    path = tmp_path / "d.md"
    text = "Intro.\n\nOld " + BAD["javascript"] + " button.\n"
    path.write_text(text, encoding="utf-8")
    svc = DocumentService(rda.MarkdownFileAdapter(path))
    out = _save(svc, text.replace("Intro.", "Intro two."))
    assert out["outcome"] == "written"
    assert BAD["javascript"] in path.read_text(encoding="utf-8")


def test_a_bad_button_in_code_or_a_plain_sentence_is_no_button():
    for text in ("`" + BAD["javascript"] + "`\n", "```\n" + BAD["javascript"] + "\n```\n",
                 "An ordinary [link](javascript:x) and a span [x]{.other onclick=y}.\n"):
        assert dec.button_fault(read_tree(text).blocks[0].ast) is None


def test_a_button_is_never_a_block_of_its_own():
    assert read_tree(BUTTON + "\n").blocks[0].type == "paragraph"


# ── the sanitiser, both layers (tests/page/test_mount_button.py runs the same CASES in browsers) ──

A = '<a href="https://example.org/x">Go</a>'
# (input, the span's attributes left, the link's attributes left)
CASES = [
    (f'<span class="button" size="m" data-variant="primary">{A}</span>', {"class": "button", "size": "m", "data-variant": "primary"},
     {"href": "https://example.org/x"}),
    ('<span class="button" size="l" data-variant="outline"><a href="/pricing">Go</a></span>',
     {"class": "button", "size": "l", "data-variant": "outline"}, {"href": "/pricing"}),
    (f'<span class="button" size="xl" data-variant="neon">{A}</span>', {"class": "button"}, {"href": "https://example.org/x"}),
    (f'<span class="button" id="b1" onclick="{PWN}" style="position:fixed" title="t" data-evil="1" data-rd-x="1" size="s">{A}</span>',
     {"class": "button", "size": "s"}, {"href": "https://example.org/x"}),
    (f'<span class="button wide" lang="fr" data-variant="secondary">{A}</span>', {"class": "button", "data-variant": "secondary"},
     {"href": "https://example.org/x"}),
    ('<span class="button" size="m"><a href="javascript:alert(1)">Go</a></span>', {"class": "button", "size": "m"}, {}),
    ('<span class="button" size="m"><a href="JaVa\nScRiPt:alert(1)">Go</a></span>', {"class": "button", "size": "m"}, {}),
    ('<span class="button" size="m"><a href="file:///etc/passwd">Go</a></span>', {"class": "button", "size": "m"}, {}),
    ('<span class="button" size="m"><a href="data:text/html,x">Go</a></span>', {"class": "button", "size": "m"}, {}),
    ('<span class="button" size="m"><a href="vbscript:x">Go</a></span>', {"class": "button", "size": "m"}, {}),
    ('<span class="button" size="m"><a href="mailto:a@example.org">Go</a></span>', {"class": "button", "size": "m"},
     {"href": "mailto:a@example.org"}),
    ('<span class="button" size="m"><a href="/x" target="_blank" onclick="' + PWN + '" title="t" download="x" ping="https://e.test">Go</a></span>',
     {"class": "button", "size": "m"}, {"href": "/x"}),
    ('<span class="button" SIZE="m" DATA-VARIANT="primary"><a HREF="/x">Go</a></span>',
     {"class": "button", "size": "m", "data-variant": "primary"}, {"href": "/x"}),
]


def tags(out, name):
    m = re.search(rf"<{name}\b([^>]*)>", out)
    assert m, out
    return dict(re.findall(r'([\w:-]+)="([^"]*)"', m.group(1)))


@pytest.mark.parametrize("mount", [False, True], ids=["page", "mounted"])
@pytest.mark.parametrize("html,span,link", CASES, ids=[f"{i:02d}" for i in range(len(CASES))])
def test_a_button_keeps_its_declared_attributes_and_a_safe_link_and_nothing_else(html, span, link, mount):
    out = sanitize(html, mount=mount)
    assert tags(out, "span") == span
    got = tags(out, "a")
    if mount and link:
        assert got.pop("rel") == "noopener noreferrer"
    assert got == link
    assert ">Go</a></span>" in out.replace("\n", "")        # the label stays when the address goes


def test_a_class_button_on_another_element_is_no_button_and_unchanged_by_this_rule():
    out = sanitize('<div class="button" data-variant="neon">x</div><p class="button" size="xl">y</p>')
    assert 'data-variant="neon"' in out and 'size="xl"' in out


def test_a_link_outside_a_button_keeps_the_page_rules():
    assert 'href="file:///x"' in sanitize('<a href="file:///x">a</a>')          # a link in text is unchanged by the button rule
    assert 'target="_blank"' in sanitize('<a href="/x" target="_blank">a</a>')


def test_the_button_survives_a_second_pass_unchanged():
    once = sanitize(f'<span class="button wide" id="b" size="m" style="x:y">{A}</span>')
    assert sanitize(once) == once


# ── the render ───────────────────────────────────────────────────────────────

def render(tmp_path, text, **kw):
    p = tmp_path / "d.md"
    p.write_text(text, encoding="utf-8")
    return sheafmd.render(p, **kw)


def main_of(out):
    return out[out.index("<main>"):out.index("</main>")]


def test_a_button_renders_as_a_span_around_one_link_in_a_paragraph_a_cell_and_a_callout(tmp_path):
    out = main_of(render(tmp_path, DOC))
    spans = re.findall(r'<span class="button"[^>]*>', out)
    assert len(spans) == 3
    assert re.search(r'<span(?=[^>]*size="m")(?=[^>]*data-variant="primary")[^>]*><a href="https://example.org/call"', out)
    assert re.search(r'<td><span(?=[^>]*size="s")(?=[^>]*data-variant="outline")[^>]*><a href="/buy"', out)
    assert re.search(r'<div[^>]*class="callout"[^>]*>.*<span(?=[^>]*size="l")(?=[^>]*data-variant="secondary")[^>]*>', out, re.S)


def test_the_reading_copy_and_the_share_copy_hold_the_same_buttons(tmp_path):
    a = re.findall(r"<span class=\"button\".*?</span>", main_of(render(tmp_path, DOC, share=False)), re.S)
    b = re.findall(r"<span class=\"button\".*?</span>", main_of(render(tmp_path, DOC, share=True)), re.S)
    assert a == b and len(a) == 3


@pytest.mark.parametrize("name", ["javascript", "javascript upper", "file", "data", "onclick", "style", "size", "variant", "target on the span"])
def test_a_bad_button_written_by_hand_comes_out_stripped(tmp_path, name):
    out = main_of(render(tmp_path, "Old " + BAD[name] + " end.\n", share=True))
    for needle in ("javascript", "JAVASCRIPT", "file:", "data:", "onclick", "style=", "xl", "neon", "target"):
        assert needle not in out, (needle, out)
    assert ">Go</a>" in out or ">Go<" in out


def test_the_base_stylesheet_gives_each_size_and_variant_a_rule_through_theme_properties(tmp_path):
    css = dec.css()
    for v in ("s", "m", "l"):
        assert f'span.button[size="{v}"]' in css
    for v in ("primary", "secondary", "outline"):
        assert f'span.button[data-variant="{v}"]' in css
    used = set(re.findall(r"var\((--sheaf-[\w-]+)", css))
    given = set(re.findall(r"(--sheaf-[\w-]+)\s*:", css))
    assert used <= given, used - given
    for p in ("--sheaf-button-primary-bg", "--sheaf-button-secondary-bg", "--sheaf-button-outline-fg", "--sheaf-button-radius"):
        assert p in given
    assert "prefers-color-scheme" not in css
    assert "span.button{" in css and "span.button>a{" in css


def test_a_theme_property_overrides_the_button_and_an_older_theme_still_lays_it_out(tmp_path):
    for name, extra in (("new", ":root{--sheaf-button-primary-bg:#abcdef}\n"), ("old", "")):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "theme.toml").write_text(f'name = "{name}"\n', encoding="utf-8")
        (folder / "theme.css").write_text(extra + "body{margin:0}\n", encoding="utf-8")
        css = re.search(r"<style[^>]*>(.*?)</style>", render(tmp_path, DOC, theme=str(folder)), re.S).group(1)
        assert "span.button{" in css and "--sheaf-button-primary-bg:" in css
        if extra:
            assert css.index("--sheaf-button-primary-bg:#abcdef") > css.index("span.button{")



def test_the_plain_theme_carries_dark_button_properties_and_the_base_css_stays_light():
    from sheafmd.theme import load_theme
    plain = load_theme("plain").css
    dark = plain[plain.index("prefers-color-scheme:dark"):]
    for p in ("--sheaf-button-primary-bg", "--sheaf-button-primary-fg", "--sheaf-button-secondary-bg", "--sheaf-button-outline-fg"):
        assert p in dark
