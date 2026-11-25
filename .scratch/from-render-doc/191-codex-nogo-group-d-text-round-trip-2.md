# 191: Codex NO-GO findings on merged PRs #576, #581, #591, #594, #595 (saving and round-trip of text, second batch)

**Claimed by:** Hugo

**Status:** open (fixes on branch `hugo/191-codex-nogo-group-d`)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. Each of the five returned NO-GO. Each finding
was reproduced against origin/main at 61783779 with pinned pandoc 3.9 (`apply_edits` or `html_block_to_md` on the
finding's own input) before anything was changed.

## Findings

- [x] [SERIOUS] #576: `\<strong>:smile:</strong>`, a typed backslash in another text node than the shortcode, saved
  the shortcode bare. Already fixed by fe75ec79 (ticket 137, `_typed_slash_before`): the page's
  `<p>\<strong>:smile:</strong> there</p>` saves as `\\**\:smile:** there`.
- [x] [SERIOUS] #581: `[http://localhost](http://localhost)` written bare, which GFM does not link. Already fixed
  by 8b8777eb (ticket 137, `_gfm_domain`): it saves as `<http://localhost>`.
- [ ] [SERIOUS] #581: `[x](<http://a\ b>)` saved as `[x](http://a\%20b)`, address changed. `_hrefs_as_words` left
  an address with white space to pandoc, which writes its backslash unescaped. Now a word too, written back by
  `_link_destination` between `<` and `>` with `\`, `<`, `>` and `|` escaped. Test:
  `tests/test_edit_191.py::test_an_address_with_a_space_and_a_backslash_keeps_both`.
- [x] [SERIOUS] #591: `<a>x</a> and [x](ftp://a.com/b)` dropped the FTP link. Already fixed by a3420561 (ticket
  137, `named_kept`/`names_dropped`): the anchor of the source's own is counted with the links, and the address
  comes back, on a plain page and on a mounted one.
- [x] [SERIOUS] #591: literal `0` in a bare anchor raised `IndexError`. Already fixed by 58cb9a44
  (ticket 137): `_emoji_as_tokens` takes the first token character the fragment does not hold, and the link's
  text is read through the tokens only when there are emoji.
- [ ] [SERIOUS] #594: in a changed part too long to diff, a typed `:smile:` beside a source `\:smile:` saved as
  `\:smile:`. `_places_by_order` now places a literal by its 12 characters of neighbours where the counts of its
  name differ, and leaves the rest bare. Tests: `test_a_typed_shortcode_in_a_long_change_stays_an_emoji_beside_an_escaped_one`,
  `test_places_by_order_where_the_counts_differ_keeps_a_literal_by_its_neighbours`; the ticket 137 test that
  asserted the old rule now asserts the new one.
- [ ] [SERIOUS] #594: `<div>\</div>:smile:` escaped the shortcode across the block boundary.
  `_typed_slash_before` now checks the backslash's own ancestors up to the one it shares with the shortcode. Test:
  `test_a_backslash_ending_a_block_does_not_escape_the_shortcode_after_it`.
- [ ] [SERIOUS] #595: `content:"x\";font-weight:700;y"` read as bold. `_declarations` now honours a backslash
  escape. Test: `test_an_escaped_quote_in_a_quoted_value_ends_no_declaration`.
- [ ] [SERIOUS] #595: `lighter` inside `font-weight:900` lifted out of the bold. `bolder` and `lighter` are now
  read against the inherited weight (`_inherited_weight`, CSS Fonts 4 table), taken before `_unwrap_strays`
  unwraps any span. Tests: `test_lighter_inside_a_heavy_span_stays_bold`, `test_lighter_inside_a_bold_span_is_plain`.
