"""`_Shift`: where an offset in the source's words lands in the page's, for a closing tag with no opener
(`_lone_as_text`). It was the closure `where` inside that function; these pin it on its own."""
from sheafmd import edit as rde


def test_an_offset_before_the_change_stays_where_it_is():
    shift = rde._Shift("one two three", "one TWO three")
    assert shift.where(3) == 3


def test_an_offset_after_the_change_moves_by_what_the_change_added():
    shift = rde._Shift("one two three", "one two and a half three")
    old_end = len("one two three")
    assert shift.where(old_end) == len("one two and a half three")


def test_an_offset_inside_the_change_goes_after_the_same_words():
    old, new = "alpha beta gamma", "alpha bet! gamma"
    shift = rde._Shift(old, new)
    # After "bet" in "beta": the letters the change kept.
    assert new[:shift.where(old.index("beta") + 3)] == "alpha bet"


def test_the_diff_is_made_only_when_an_offset_falls_inside_the_change():
    shift = rde._Shift("one two three", "one TWO three")
    shift.where(0)
    shift.where(len("one two three"))
    assert "same" not in vars(shift)
    shift.where(len("one t"))
    assert "same" in vars(shift)


def test_far_apart_edits_place_an_offset_by_the_words_around_it():
    filler = "x" * (rde.LONE_DIFF_MAX + 10)
    old = "start " + filler + " middle words here " + filler + " end"
    new = "START " + filler + " middle words here " + filler + " END"
    shift = rde._Shift(old, new)
    o = old.index("words")
    assert new[shift.where(o):].startswith("words here")
    assert "same" not in vars(shift)
