# 201: Codex NO-GO findings on merged PR #656 (group J, edit.py break runs and heading remnants)

**Claimed by:** Alonso

**Status:** claimed

**Blocked by:** none

**From:** the Codex re-check of #656 (ticket 188's fix), round 05, NO-GO. Two findings, both marked serious.

**Where:** `src/sheafmd/edit.py`: `_split_at_double_breaks` (which run of breaks is the source's), `_lines_as_paragraphs` (`remnant`, what an emptied first half of a split heading leaves).

## Serious

- [ ] **A** (`_split_at_double_breaks`): a run of the source's hard breaks is recognised only when a line beside it stays unchanged; editing both lines in one save splits one paragraph into two, and a new run nearby can take the old run's match.
- [ ] **B** (`_lines_as_paragraphs`, `remnant`): every empty inline element but an image or a box is taken for a remnant and deleted when the second half of a split heading becomes the heading, so an empty link target (`<a id="x"></a>`) is lost.
