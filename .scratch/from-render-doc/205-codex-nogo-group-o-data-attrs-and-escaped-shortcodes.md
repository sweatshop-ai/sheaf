# 205: Codex NO-GO findings on merged PR #670 (group O, edit.py data attributes and escaped shortcodes)

**Claimed by:** Alonso

**Status:** done: merged in #689 (c9e928fb) on 2026-11-26, CI `ubuntu-24.04 py3.13` run 45735293803: 11337 passed, one failure, `test_land_root`, which is main's own until #677 lands

**Blocked by:** none

**From:** the Codex re-check of #670 (ticket 197's fix), round 02, NO-GO. Two findings, both marked serious.

**Where:** `src/sheafmd/edit.py`: `_strip_tag_data` / `strip_data_attrs` (a `data-` attribute right after a `/`), `_in_its_gap` (which `:name:` of a changed stretch an escaped shortcode takes).

## Serious

- [x] **A** (`strip_data_attrs`): `strip_data_attrs("<div/data-x>")` returns `<div/>`, a tag that closes itself, where the parser reads a `<div>` that stays open with a `data-x` attribute; raw HTML nobody touched can then compare as changed and be rewritten. Fix: when a dropped attribute leaves a `/` last before `>` in a tag that did not end in `/>`, what follows the tag's name or the last name or value kept goes; a bare value that ends in `/` keeps it, with a space before the `>` (`<a href=x/ /data-x>` is `<a href=x/ >`).
  Tests: `tests/test_edit_205.py`, `test_a_data_attribute_right_after_a_slash_leaves_the_tag_as_open_as_the_parser_read_it` (9 tag shapes, each checked against `html.parser`); `tests/test_edit_data_attr_values.py` pinned `<a/>x</a>` and expects `<a>x</a>`.
- [x] **B** (`_in_its_gap`): a `:name:` chosen for one escaped shortcode is not reserved, so two escaped shortcodes of a long changed stretch can take the same one; the other then shows as its emoji. Fix: a place `_in_its_gap` gives a literal is given to no other, and the one the diff had matched it to is free again.
  Test: `test_two_escaped_shortcodes_in_one_changed_stretch_keep_their_escapes_at_two_places` (past the characters' diff, within the words').

## Left open

- [ ] **B2** (minor, from the review of #689): in the layout of the finding (`\\:s: \\:s: a b` to `:s: :s: x :s: a b`) the two escapes go to the second and third `:s:`, not the first and second (or first and third): the diff matched the first literal to the first `:s:`, and ticket 197's rule (#658) moves a literal to the place at the same share of its changed stretch. Both escapes are kept and no text is lost; which `:s:` the reader typed is not in the saved HTML, and changing the share rule reopens #658.

## Notes

- Review of #689: Matt's code review (standards: style points, applied; spec: the `/` of a bare value stripped, fixed, and B2 above), then Codex b, which gave no verdict: Opus fallback GO with two minors (the same `/`, a test case that tested nothing), fixed in 2ce8b83e; GO on that diff (round 02).
- Two same-name literals placed crossed (`[18, 10]`) write the same text as `[10, 18]`, so it is no defect.
- Outside this ticket, and the same on main before it: two lone literals in two changed stretches of about 1 000 words each keep only one escape.
