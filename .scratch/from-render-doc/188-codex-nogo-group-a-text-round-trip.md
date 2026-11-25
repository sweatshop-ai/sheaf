# 188: Codex NO-GO findings on merged PRs #559, #555, #494, #571, #554 (saving and round-trip of text)

**Claimed by:** Kenji

**Status:** in progress (fixes on branch `kenji/188-codex-nogo-group-a`)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. Each of the five returned NO-GO: #559 (round 6), #555 (round 6), #494 (round 7), #571 (round 6), #554 (round 8). Every finding was checked against main aa22990a.

**Counts:** 13 findings:

- 2 serious, both still present on main: A, F.
- 8 minor still present on main: B, C, D, E, G, H, I (fixed, one case left open), J (left open).
- 3 already fixed on main (#555 findings 1, 3, 4): see the last section.
- Part of I left open: see its box.

Ratings follow the rule of ticket 183. Serious means a wrong result in ordinary use, a crash, data loss, or a security or privacy breach. Minor means the defect needs narrow input, a narrow race or an unusual setup, or it only changes a status code, a log row or the form of the source. Codex rated all 13 serious.

**Where:** `src/sheafmd/edit.py` (A, B, C, F, G, H), `src/sheafmd/page/page.js` (F), `src/sheafmd/orderedtask.py` (D, E, J), `src/sheafmd/mcp.py` (I).

Each box has a red test written on main first. Tests: `tests/test_edit_188_codex_nogo.py`; I in `tests/test_share.py`; F's page half in `tests/page/test_page_writing.py` (CI only).

## Serious

- [ ] **A (#559, finding 1): a markdown hard break of the source is taken for a new one.** `_unwrap_strays` counted the tags the source had in its markdown, where a hard break is `\` or two trailing spaces, never a `<br>`. Both breaks of `Alpha\` `\` `Beta` were counted as new, so any edit of that paragraph split it into two paragraphs. Fix: `_split_at_double_breaks` reads the runs of breaks in the source's render (the cached one `_unchanged` asked for), and a run of the page with the same length and the same line on one side of it is the source's own, not a new paragraph break. The first version counted the render's breaks against the page's in page order; the review round showed two new breaks before an old one then lost their split. Tests: `test_the_hard_breaks_of_the_source_stay_breaks_when_the_paragraph_is_edited`, `test_two_new_breaks_in_a_paragraph_with_a_break_of_its_own_still_make_two_paragraphs` (new breaks before or after the source's own, beside a raw `<br>`, beside the source's own run).
- [ ] **F (#571, finding 1): Enter after a heading's last word and before its comment makes the next line a heading.** The page read the words after the caret with its own UI in them, the comment anchor's numbered badge, and marked the line `data-rd-split`; the hub then counted the comment's placeholder as the half's words. Fix: the page drops `[data-rd-ui]` from the words it reads; the hub reads a split line's words without the comment placeholders. Tests: `test_a_split_line_holding_only_a_comment_is_a_paragraph_not_a_heading`, and the browser test `test_enter_after_a_headings_last_word_and_before_its_comment_makes_a_paragraph`.

## Minor

- [ ] **B (#559, finding 2): a double break with no words before it ended the scan of the paragraph.** In `<p><br><br>Alpha<br><br>Beta</p>` the break between Alpha and Beta stayed two hard breaks. Fix: `_split_at_double_breaks` lists every run of new breaks and splits at the first one with words on both sides. Test: `test_a_double_break_with_no_words_before_it_leaves_the_next_one_to_split`.
- [ ] **C (#555, finding 2): tag-shaped text inside an HTML comment lost its data attributes in the source render only.** `<!-- <span data-x="1"> -->` became `<!-- <span> -->` on the source side while `_sanitize` kept the comment whole, so the block never compared equal and its boxes did not tick. Fix: `strip_data_attrs` passes over comments whole. Test: `test_a_data_attribute_written_inside_an_html_comment_is_kept_on_both_sides`.
- [ ] **D (#494, finding 1): `</p>` or `<div` inside an attribute value or a comment ended an ordered task's label.** `show` searched the raw HTML for the end and cut a quoted value in two. Fix: the end is looked for tag by tag, quoted values and comments read whole (`orderedtask._label_end`). Test: `test_tag_shaped_text_inside_an_ordered_task_label_does_not_end_the_label`.
- [ ] **E (#494, finding 3): a CR inside an ordered task mark left the characters instead of a box.** Pandoc deletes every CR before it reads; `hide` read the mark with the CR still in it. Fix: `hide` deletes CRs first (the source positions pandoc reports are those of the text without CRs already, `comments._kept`). Tests: `test_a_carriage_return_in_an_ordered_task_mark_still_draws_the_box`, `test_hide_drops_carriage_returns_as_pandoc_does`.
- [ ] **G (#571, finding 2): an emptied first half with an empty mark left in it stayed as an empty heading.** `<h2><em></em><div data-rd-split>cd</div></h2>` saved as `## ` then `## cd`. Fix: an inline element with no text, no image and no box counts as a remnant and goes when the half is promoted; a comment's placeholder still counts as words. Tests: `test_an_emptied_first_half_with_an_empty_mark_left_in_it_goes`, `test_a_first_half_with_a_comment_in_it_is_not_empty`.
- [ ] **H (#571, finding 3): the no-break space Enter leaves stayed in a promoted half.** Fix: the half is trimmed at its start before it is unwrapped. Test: `test_the_cut_space_goes_from_a_half_that_becomes_the_heading`.
- [ ] **I (#554): an error text swapped the start of a longer name for the opaque name.** `plan.md+copy.md`, `plan.md~` were rewritten. Fix: `~`, `+`, `#` and `=` after the address continue a name, as a word character, `/`, `-` and `.` then a word character already did; anything else after it ends the address and it is swapped (`plan.md:3:`, `plan.md's`), so the owner's folders are never left in the text. Test: `test_an_error_text_leaves_a_longer_name_with_other_punctuation_alone` (red on main for `+copy.md`, `~`, `#2`, `=x`). Left open: `plan.md (copy).md`, a name with a space in it, cannot be told from the address followed by words in brackets.
- [ ] **J (#494, finding 2): a document holding U+E000 or U+E001 draws no ordered task box, and a pair of them may show as `[ ]`.** Left open: a fix needs an escape for these characters across `hide`, `show`, the emoji read and the comment projection (`comments.py` maps the stand-ins to `[` and `]` character by character); the input is a private-use character a document is very unlikely to hold.

## Already fixed on main

- #555 finding 1 (a `data-` inside a quoted value was taken for an attribute): 9e9d08dc (ticket 187 BZ).
- #555 finding 3 (`DATA-X` kept in the source render): 9e9d08dc, `_DATA_NAME_RE` with `re.I`.
- #555 finding 4 (`data-rd-*` kept in the source render): f1164b71 (ticket 187 review round), `_DATA_NAME_RE` strips the page's own too.
