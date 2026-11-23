"""Links and bare URLs keep their address and text on a page edit (ticket 137, the backslash and URL items).

A bare URL in a table pandoc writes as raw HTML lost its link; pandoc's `<url>` was unwrapped where GFM does not
link a bare URL (after a word character, or with a mark at its end GFM trims); and a link's address was written
as pandoc leaves it, so a backslash in it read back as an escape and a lone `)` ended it.
"""
import re

import pytest

from sheafmd import edit as rde
from test_edit_backslash import page_fragment, saved


def anchors(fragment):
    return re.findall(r'<a href="([^"]*)"', fragment)


def words(fragment):
    return " ".join(re.sub(r"<[^>]*>", " ", fragment).split())


def same_page(src, out, new="there"):
    want, got = page_fragment(src.replace("here", new)), page_fragment(out)
    assert anchors(got) == anchors(want)
    assert words(got) == words(want)


# A pipe table with a break typed in a cell and a backslash in another cell's text: pandoc writes it as raw HTML.
@pytest.mark.parametrize("url", ["http://x.com/a\\\\b", "http://x.com/ab"])
def test_a_bare_url_in_a_table_pandoc_writes_as_raw_html_stays_a_link(url):
    src = f"| a | b |\n|---|---|\n| see {url} | c\\\\d here |"
    out = saved(src, new="there<br>more")
    assert out.lstrip().startswith("<table")
    same_page(src, out, new="there<br>more")


@pytest.mark.parametrize("src", [
    "x[http://x.com/a\\b](http://x.com/a\\b) here",
    "x[http://x.com/ab](http://x.com/ab) here",
    "[http://x.com/ab](http://x.com/ab)x here",
])
def test_a_link_whose_text_is_its_address_next_to_a_word_character_stays_a_link(src):
    same_page(src, saved(src))


@pytest.mark.parametrize("src", ["see <http://x.com/ab.> here", "see <http://x.com/ab,> here",
                                 "see <http://x.com/ab)> here"])
def test_a_bare_url_ending_in_a_mark_gfm_trims_keeps_the_mark(src):
    same_page(src, saved(src))


@pytest.mark.parametrize("src", ["see http://x.com/ab. here", "(see http://x.com/ab) here",
                                 "see *http://x.com/ab* here", "see http://x.com/a\\b here",
                                 "see http://x.com/a(b) here"])
def test_a_bare_url_gfm_links_as_written_is_still_written_bare(src):
    out = saved(src)
    same_page(src, out)
    assert "<http" not in out


@pytest.mark.parametrize("src", [
    r"[x](http://a\\\\b) here",
    r"[x](http://a\\\*b) here",
    r"[x](http://a\\b\\) here",
    r"[x](http://a\\\(b) here",
    r"[x](http://a.com/b\)) here",
])
def test_a_link_address_keeps_its_backslashes_and_parentheses(src):
    same_page(src, saved(src))


def test_a_link_address_with_a_backslash_in_a_raw_html_table_keeps_it():
    src = "| a | b |\n|---|---|\n| [x](http://a\\\\\\\\b) | c\\\\d here |"
    out = saved(src, new="there<br>more")
    assert out.lstrip().startswith("<table")
    same_page(src, out, new="there<br>more")


def test_a_table_sent_back_to_pandoc_whole_still_drops_the_break_that_ends_a_cell(monkeypatch):
    # Pandoc's writer can take a character of the cut's token; the table then goes again as raw HTML. That run
    # starts from the text the cuts were sorted in: a break that ends its cell and Enter's no-break space go.
    real = rde._pandoc.run

    def run(args, text):
        r = real(args, text)
        tok = next((c for c in r.stdout if 0xE000 <= ord(c) < 0xF000), None)
        if args[:4] == ["-f", "html", "-t", "gfm"] and tok is not None:
            r.stdout = r.stdout.replace(tok, "", 1)
        return r

    monkeypatch.setattr(rde._pandoc, "run", run)
    frag = ("<table><thead><tr><th>h</th><th>k</th></tr></thead><tbody><tr>"
            "<td>a<br>b</td><td>c<br>\xa0</td></tr></tbody></table>")
    out = rde.html_block_to_md(frag)
    assert out.startswith("<table")
    assert re.findall(r"<td>(.*?)</td>", re.sub(r"\s*\n\s*", "", out)) == ["a<br />b", "c"]


# Ticket 183 AI: GFM keeps a `)` at the end of a bare URL its own `(` balances, so the URL with a backslash goes as a
# word too.
@pytest.mark.parametrize("src", [r"see http://x.com/a(\*b) here", r"see http://x.com/a(\\b) here",
                                 r"see http://x.com/a\b(c) here"])
def test_a_bare_url_with_a_backslash_ending_in_a_balanced_parenthesis_stays_a_link(src):
    out = saved(src)
    same_page(src, out)
    assert anchors(page_fragment(out)) == anchors(page_fragment(src)) != []


# Ticket 183 BB: which `)` GFM keeps at the end of a bare URL is pandoc's own reading, not a count of parentheses: after
# `(*` or `(\*` it keeps a `)` no `(` balances, and after `)*(` it ends the URL before the `)`.
@pytest.mark.parametrize("src", [r"see http://x.com/a(\*b)) here", r"see http://x.com/a(x\*b)) here",
                                 r"see http://x.com/a\b)*(c) here"])
def test_a_bare_url_with_a_backslash_whose_parentheses_do_not_balance_keeps_its_text(src):
    out = saved(src)
    same_page(src, out)
    assert anchors(page_fragment(out)) == anchors(page_fragment(src)) != []


# Ticket 183 BT: a failed run of the link probe is not remembered; it refuses that save, and the next one asks again.
def test_a_failed_look_at_a_bare_url_is_not_kept_for_the_next_save(monkeypatch):
    src = r"see http://x.com/a(\*b)) here"
    rde._pandoc_links_bare.cache_clear()
    real, failed = rde._pandoc.run, []

    def probe_fails_once(args, text):
        r = real(args, text)
        if text.startswith("x http") and not failed:
            failed.append(1)
            r.returncode = 1
        return r

    monkeypatch.setattr(rde._pandoc, "run", probe_fails_once)
    doc = "# Title\n\n" + src + "\n"
    try:
        out, rep = rde.apply_edits(doc, [{"i": 1, "html": page_fragment(src).replace("here", "there")}])
        assert failed and out == doc and [i for i, _ in rep["skipped"]] == [1]
        same_page(src, saved(src))
    finally:
        rde._pandoc_links_bare.cache_clear()
