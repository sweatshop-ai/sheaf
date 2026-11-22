"""Shortcode follow-ups of a page edit (ticket 137): a raw-HTML table, a shortcode typed as text, a failed look."""
from sheafmd import edit as rde
from test_edit_emoji import page_fragment, saved


def test_a_shortcode_in_a_table_pandoc_writes_as_raw_html_keeps_its_emoji():
    src = "| :+1: | here |\n|---|---|\n| a | b |"
    doc = "# Title\n\n" + src + "\n"
    html = page_fragment(src).replace("here", "<ul><li>x</li><li>y</li></ul>")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    assert "<table" in out and "<th>👍</th>" in out and ":+1:" not in out


def test_a_shortcode_typed_as_text_stays_text():
    out = saved("a \\:smile: here")
    assert out == "a \\:smile: there\n"
    assert "emoji" not in page_fragment(out)


def test_a_shortcode_that_is_no_emoji_is_not_escaped():
    assert saved("a :nonesuch: here") == "a :nonesuch: there\n"


def test_a_failed_look_at_an_emoji_is_not_kept(monkeypatch):
    rde._emoji_drawn.cache_clear()
    real = rde._pandoc.run
    calls = []

    def once_failing(*a, **k):
        calls.append(1)
        r = real(*a, **k)
        if len(calls) == 1:
            r.returncode = 1
        return r

    monkeypatch.setattr(rde._pandoc, "run", once_failing)
    assert rde._emoji_drawn("tada") is None
    assert rde._emoji_drawn("tada") == "\U0001F389"
    rde._emoji_drawn.cache_clear()
