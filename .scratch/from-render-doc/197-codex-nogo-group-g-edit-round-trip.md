# 197: Codex NO-GO findings on merged PRs #631, #634, #637, #642 and #658 (group G, edit round-trip)

**Claimed by:** Yohana

**Status:** in review (A to D fixed on the branch)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. All five returned NO-GO (#631 round 06, #634 round 07, #637 round 06, #642 round 07, #658 round 04). Every finding was checked against main 3b984afe. Boxes are lettered A to D within this ticket ("197 A").

**Counts:** 7 findings, all marked serious by Codex:

- 2 already fixed on main (last section).
- 5 still present, all fixed here, each with a red test on main first (`tests/test_edit_197.py`, 11 cases).

**Where:** `src/sheafmd/edit.py`: `_lone_as_text` (the climb of a closing tag with no opener), `_strip_tag_data` (the `data-` attributes of a start tag), `_places_by_order` with the new `_in_its_gap` (an escaped shortcode in a long change), `_inherited_weight` (a mark's own weight).

## Serious

- [ ] **A** (from #634, `_lone_as_text`): a closing tag with no opener at the start of an item climbs out of the elements between it and the words after it. Where a comment stood between two of those elements (`- </x1>*<!-- f1 -->**Start** rest*`), the climb stopped at the text holding the comment, stepped over it, and never climbed out of the outer element: the tag was saved inside the emphasis (`- *</x1><!-- f1 -->**Start** rest*`). The same held after words (`*a **Start<!-- f2 -->**<!-- f1 -->*</x1>`). Fix: climbing and stepping over comments alternate until the climb count is used up; a text that holds only the comments to step over is crossed whole and the climb goes on from there.
  Tests: `test_a_closing_tag_with_no_opener_climbs_out_of_every_element_past_the_comments_between_them` (3 cases).
- [ ] **B** (from #642, `_strip_tag_data`, two findings): its own attribute pattern took any number of `=` as the value indicator, where the page's parser (html.parser, in `_sanitize`) takes one on the Python releases in use: `<div data-x == title>` lost `title`, and `<div title == data-x=1>` kept `data-x`. And a dropped attribute took the white space before it with it, so one glued to the next (`<div data-x="1"title=a'b>`) became `<divtitle=a'b>`. Both made `_unchanged` see a change in an untouched raw-HTML block and send it through pandoc. Fix: the tag name and each attribute are read with html.parser's own `tagfind_tolerant` and `attrfind_tolerant`, so the two agree on every Python release; an attribute is dropped with the white space after it (the white space, quote or `/` before it stays), and the white space a dropped attribute leaves at the end is trimmed (not before a `/>` after a bare value, which would take the `/`).
  Tests: `test_data_attributes_go_and_the_others_stay_as_the_parser_reads_them` (5 cases, checked against the parser's own reading).
- [ ] **C** (from #658, `_places_by_order`): with every word around an escaped shortcode changed and the same `:name:` typed elsewhere, the word diff matched the literal to the first `:name:` in the gap, which was the typed one: the typed shortcode was saved escaped and the source's literal became an emoji. The count-only test of #658 did not see the swap. Fix (`_in_its_gap`): among the `:name:` between the nearest words that still match on either side, and that no other word matched, the literal goes to the one at the same share of the way between them.
  Test: `test_an_escaped_shortcode_among_changed_words_keeps_its_escape_at_its_place` (asserts the whole saved text, not counts).
- [ ] **D** (from #658, `_inherited_weight`): a `<b>`'s default `bolder` was applied and then its own `font-weight` read against that, where CSS replaces the default with the element's own declaration, read against the parent. Inside 500, `<b style="font-weight:lighter"><span style="font-weight:bolder">` was saved bold (it shows at 400). Fix: an element's own weight, when it has one, is read from its parent's and replaces the default of a `<b>`, `<strong>` or heading.
  Tests: `test_a_bold_tag_whose_own_style_says_lighter_is_read_from_its_parent`, `test_a_bold_tag_whose_own_style_says_bolder_is_bolder_once`.

## Already fixed on main

- **#631** (`_lone_as_text`, `lead`/`trail` held only comment counts, so deleting `c1` from `Start<c1></x1><c2>` stepped the tag over `c2`): fixed by 899a25cf (#634, ticket 183 BX), which records the comments themselves and steps over only those. Test on main: `test_a_closing_tag_with_no_opener_steps_over_only_the_comments_that_stood_beside_it[sheaf-before-deleted]`.
- **#637** (`_START_TAG_RE` took any quote for an opening one, so `<a href=a'b data-x=1>` kept `data-x`): fixed by 11b72450, merged in 505b328e (#642). Test on main: `test_a_quote_inside_a_bare_value_or_a_name_is_no_quoted_value`.

## Notes

- `tests/test_edit_137_followups.py`'s three CPU-time cases for a long block fail on the laptop under load on main and on this branch alike (about 1.0 to 1.3 s against a 1.0 s limit, load 15); the profile of that case shows the same call count on both, and none of the code changed here runs in it. CI on the CI runner host is the measure.
