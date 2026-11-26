"""Ticket 207: two lone escaped shortcodes in two long changed stretches each keep their escape.

Two changed stretches of about 1 000 words each, with words between them that did not change, are each within the
bound of the word diff, though the two together are past it. Each stretch is diffed on its own, so that each escaped
`\\:name:` whose neighbours changed keeps its escape, and a `:name:` the reader typed stays the emoji.
"""
import random
import time

from test_edit_191 import saved_as

from sheafmd import edit as rde


def _words(prefix, n=500):
    return " ".join(f"{prefix}{i}" for i in range(n))


_MIDDLE = "an unchanged sentence stands between the two changed stretches here"


def test_two_lone_escapes_in_two_long_changed_stretches_keep_both_escapes():
    src = f"{_words('a')} \\:smile: {_words('b')} {_MIDDLE} {_words('c')} \\:smile: {_words('d')} end"
    html = f"<p>{_words('A')} :smile: {_words('B')} {_MIDDLE} {_words('C')} :smile: {_words('D')} :smile: end</p>"
    out = saved_as(src, html)
    assert out.count("\\:smile:") == 2, out.count("\\:smile:")
    assert out.endswith("D499 :smile: end\n"), out[-30:]       # the one the reader typed stays the emoji
    assert "A499 \\:smile: B0" in out and "C499 \\:smile: D0" in out


def test_by_words_diffs_each_stretch_between_unchanged_words_on_its_own():
    old = f"{_words('a')} x :smile: {_words('b')} {_MIDDLE} {_words('c')} y :smile: {_words('d')}"
    new = f"{_words('A')} x :smile: {_words('B')} {_MIDDLE} {_words('C')} y :smile: {_words('D')}"
    words = rde._by_words(old, new)
    assert words is not None
    for name in ("x :smile:", "y :smile:", "between"):
        assert words[old.index(name)] == new.index(name), name


def test_many_long_stretches_stop_at_the_total_and_do_not_grow_with_their_square(no_gc):
    # Forty stretches at the bound, of a few words repeated (the diff's dearest case), with an unchanged word after
    # each: the diff stops once the stretches add up past `_DIFF_TOTAL`, and the literals go to their neighbours.
    rng = random.Random(207)
    vocab = [f"w{i}" for i in range(30)]

    def text():
        return " ".join(" ".join(rng.choice(vocab) for _ in range(1400)) + f" keep{s}" for s in range(40))

    old, new = text(), text()
    t = time.process_time()
    assert rde._by_words(old, new) is None
    assert time.process_time() - t < 1.0


def test_a_chain_of_cuts_that_each_find_one_word_stops_at_the_total(no_gc):
    # Each cut finds one word once on each side, near the end of its stretch: the cuts' own counting stops at the
    # total too (`_CUT_WEIGHT`).
    rng = random.Random(207)
    vocab = [f"w{i}" for i in range(30)]
    head_a = [rng.choice(vocab) for _ in range(1600)]
    head_b = [rng.choice(vocab) for _ in range(1600)]
    ta, tb = ["x1"], ["x1", "j"]
    for k in range(2, 3001):
        ta += [f"x{k}", f"x{k - 1}"]
        tb += [f"x{k}", "j", f"x{k - 1}", "j"]
    old, new = " ".join(head_a + ta), " ".join(head_b + tb)
    t = time.process_time()
    rde._by_words(old, new)
    assert time.process_time() - t < 0.3
