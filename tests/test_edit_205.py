"""Ticket 205: the Codex NO-GO findings on #670 (ticket 197's fix).

A `data-` attribute right after a `/` keeps the tag open as the parser reads it, and two escaped shortcodes in one
changed stretch each keep their escape at a `:name:` of their own.
"""
import pytest
from test_edit_191 import saved_as
from test_edit_197 import _parsed

from sheafmd import edit as rde


# 670, A: a `data-` attribute dropped right after a `/` leaves no `/>` behind it.

@pytest.mark.parametrize("tag", [
    "<div/data-x>",
    "<div /data-x>",
    "<div/data-x=1>",
    "<a href=x/ /data-x>",
    "<a href=/ /data-x>",
    "<a href=x/\t/data-x>",
    "<div title='t'/data-x>",
    "<div/data-x/data-y>",
    "<div/data-x/>",
])
def test_a_data_attribute_right_after_a_slash_leaves_the_tag_as_open_as_the_parser_read_it(tag):
    out = rde.strip_data_attrs(tag)
    name, attrs, closed = _parsed(tag)
    assert _parsed(out) == (name, [(n, v) for n, v in attrs if not n.startswith("data-")], closed), out


# 670, B: two escaped shortcodes in one long changed stretch do not take the same `:name:`.

def test_two_escaped_shortcodes_in_one_changed_stretch_keep_their_escapes_at_two_places():
    # past the bound of the characters' diff, within that of the words' (`_by_words`), where `_in_its_gap` places them
    old_a = " ".join(f"w{i}" for i in range(1000))
    new_a = " ".join(f"v{i}" for i in range(1000))
    out = saved_as(f"{old_a} \\:smile: \\:smile: a b", f"<p>{new_a} :smile: :smile: x :smile: a b</p>")
    assert out.count("\\:smile:") == 2, out[-60:]
