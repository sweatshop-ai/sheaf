"""Every page, article, tool or document a text names is a link.

Two halves: the rule the page hands to an agent, and a render-time warning for a host
name or site path that sits in prose without a link. The warning must stay quiet on a
clean document, or nobody reads it the day it matters.
"""
from pathlib import Path

from sheafmd import links


def names(html, **kw):
    return [m for m, _ in links.unlinked_mentions(html, **kw)]


# ── the detector ────────────────────────────────────────────────────────────

def test_a_host_and_path_in_prose_are_reported():
    assert names("<p>See example.com/pricing for the plans.</p>") == ["example.com/pricing"]


def test_a_subdomain_is_reported_without_the_sentence_full_stop():
    assert names("<p>The figures come from data.example.com.</p>") == ["data.example.com"]


def test_a_scheme_and_a_query_string_stay_in_the_mention():
    assert names("<p>Open https://shop.example.be/a/b?x=1&amp;y=2, then go on.</p>") == [
        "https://shop.example.be/a/b?x=1&y=2"]


def test_the_same_mention_twice_is_reported_once_with_where_it_first_stands():
    found = links.unlinked_mentions("<p>Try example.com/a today.</p><p>Or example.com/a later.</p>")
    assert [m for m, _ in found] == ["example.com/a"]
    assert "Try example.com/a today." in found[0][1]


def test_a_mention_inside_a_link_is_quiet_whatever_the_link_says():
    assert names('<p>See <a href="https://www.example.com/pricing">www.example.com/pricing</a>.</p>') == []
    assert names('<p>See <a href="https://www.example.com/x">the pricing page</a> now.</p>') == []


def test_only_the_unlinked_one_is_reported_when_both_stand_in_one_paragraph():
    html = '<p><a href="https://a.example.com/x">a.example.com/x</a> and b.example.com/y</p>'
    assert names(html) == ["b.example.com/y"]


def test_fenced_code_and_a_code_sample_are_left_alone():
    assert names("<pre><code>curl https://www.example.com/x\nwww.example.com</code></pre>") == []
    assert names("<p>Run <code>curl www.example.com/x</code> first.</p>") == []


def test_inline_code_holding_one_host_is_a_reference_and_is_reported():
    assert names("<p>The sitemap is at <code>www.example.com/sitemap.xml</code>.</p>") == [
        "www.example.com/sitemap.xml"]


def test_html_comments_and_attributes_are_not_prose():
    assert names("<p>Text<!-- rd-comment: see www.example.com/x --> more.</p>") == []
    assert names('<p><img src="https://cdn.example.com/a.png" alt="cdn.example.com"></p>') == []


def test_an_email_address_is_not_a_site():
    assert names("<p>Write to ada@example.com or ada@mail.example.com.</p>") == []


def test_file_names_and_abbreviations_are_not_sites():
    html = ("<p>Edit notes.txt or audit-2026-10.md and config.json, i.e. the file, e.g. "
            "Node.js, v1.2, version 3.14, and Dr. Smith.</p>")
    assert names(html) == []


# ── the warning text ────────────────────────────────────────────────────────

def test_the_warning_names_each_mention_and_says_to_make_it_a_link():
    text = links.warning(links.unlinked_mentions(
        "<p>The terms are on example.com/terms, and the data on data.example.com.</p>"))
    assert "2 host name(s)" in text
    assert "example.com/terms" in text and "data.example.com" in text
    assert "markdown link" in text and "curl" in text


def test_the_warning_stops_at_its_limit_and_counts_the_rest():
    found = [(f"a{i}.example.com", "ctx") for i in range(5)]
    text = links.warning(found, limit=2)
    assert "a1.example.com" in text and "a2.example.com" not in text
    assert "and 3 more" in text


# ── the rule the page hands to an agent ─────────────────────────────────────

def test_the_rule_says_link_check_and_add_nothing_generic():
    rule = links.RULE
    assert "markdown link" in rule and "https://" in rule
    assert "curl" in rule
    assert "generic" in rule


# ── the default endings and the extra ones ──────────────────────────────────

STUDIO = "<p>The portfolio is at acme.example.studio/work and the shop at example.com/shop.</p>"


def test_the_default_endings_are_still_one_string_and_the_module_regex_is_built_from_it():
    assert isinstance(links.TLDS, str)
    assert links.TLDS.split("|")[:3] == ["com", "org", "net"]
    assert "studio" not in links.TLDS.split("|")
    assert links.HOST.pattern == links._host_regex(()).pattern
    assert f"(?P<tld>{links.TLDS})" in links.HOST.pattern


def test_an_ending_outside_the_default_list_is_not_reported_by_default():
    assert names(STUDIO) == ["example.com/shop"]
    assert names(STUDIO, extra_tlds=()) == ["example.com/shop"]
    assert names(STUDIO, extra_tlds=None) == ["example.com/shop"]


def test_an_extra_ending_is_reported_and_the_default_ones_still_are():
    assert names(STUDIO, extra_tlds=["studio"]) == ["acme.example.studio/work", "example.com/shop"]


def test_extra_endings_may_come_with_a_leading_dot_or_in_capitals():
    want = ["acme.example.studio/work", "example.com/shop"]
    for given in ([".studio"], ["STUDIO"], [".Studio"], ["Studio", ".STUDIO", "studio"]):
        assert names(STUDIO, extra_tlds=given) == want, given


def test_extra_endings_may_be_any_iterable_and_a_bare_string_is_one_ending():
    want = ["acme.example.studio/work", "example.com/shop"]
    assert names(STUDIO, extra_tlds=("studio",)) == want
    assert names(STUDIO, extra_tlds=(e for e in ["studio"])) == want
    assert names(STUDIO, extra_tlds="studio") == want
    # a bare string is not read letter by letter: "s" and "t" are not endings here
    assert names("<p>See acme.s and acme.t today.</p>", extra_tlds="st") == []


def test_extra_endings_with_digits_work():
    assert names("<p>See example.b2b/offer today.</p>", extra_tlds=["b2b"]) == ["example.b2b/offer"]


def test_an_extra_ending_is_a_whole_ending_not_the_start_of_a_longer_word():
    assert names("<p>See acme.studios and acme.studio.</p>", extra_tlds=["studio"]) == ["acme.studio"]
    assert names("<p>The file acme.studio_notes is here.</p>", extra_tlds=["studio"]) == []


def test_an_extra_ending_works_inside_lone_inline_code_too():
    html = "<p>The site is <code>acme.studio/work</code> and a sample is <code>curl acme.studio</code>.</p>"
    assert names(html) == []
    assert names(html, extra_tlds=["studio"]) == ["acme.studio/work"]


def test_an_ending_already_in_the_default_list_changes_nothing():
    html = "<p>See example.com/pricing and data.example.be.</p>"
    assert names(html, extra_tlds=[".COM", "be"]) == names(html)
    assert links._host_regex(links._clean_extra([".COM", "be"])) is links.HOST


def test_an_invalid_ending_is_ignored_and_never_makes_the_regex_invalid():
    html = "<p>See example.com/pricing, acme.a, acme.x and acme.b.</p>"
    bad = ["a b", "x)", "(", "a|b", ".*", "[a-z]", "x\n", "", ".", "..b", "é", "a.b", 7, None]
    assert links._clean_extra(bad) == ()
    assert names(html, extra_tlds=bad) == names(html) == ["example.com/pricing"]
    # one good ending among the bad ones still counts
    assert names("<p>acme.studio and acme.x</p>", extra_tlds=["x)", "studio", "a b"]) == ["acme.studio"]


def test_one_compiled_regex_per_distinct_set_whatever_the_order_or_spelling():
    one = links._host_regex(links._clean_extra(["b2b", ".Studio"]))
    two = links._host_regex(links._clean_extra(["studio", "B2B", "studio"]))
    assert one is two
    assert one is not links.HOST
    assert links._host_regex(links._clean_extra([])) is links.HOST


def test_the_default_call_gives_the_same_answer_as_before_the_extra_endings_existed():
    html = ("<p>See example.com/pricing, data.example.com, https://shop.example.be/a/b?x=1 and "
            "<code>www.example.com/sitemap.xml</code>; edit notes.txt and Node.js.</p>")
    assert names(html) == ["example.com/pricing", "data.example.com",
                           "https://shop.example.be/a/b?x=1", "www.example.com/sitemap.xml"]


# ── what the module may say about whom it was written for ────────────────────

def test_the_source_does_not_describe_the_sites_of_one_agency():
    source = Path(links.__file__).read_text(encoding="utf-8")
    assert "this agency's work" not in source
    assert "ordinary web writing" in source
    assert links.__doc__.splitlines()[0].startswith("sheafmd.links — ")
