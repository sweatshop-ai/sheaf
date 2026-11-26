# 207: two lone escaped shortcodes in two long changed stretches keep only one escape

**Claimed by:** Kenji

**Status:** done, merged in #691 (57e6f31f)

**Blocked by:** none

**From:** found while working on ticket 205 (see its handoff, 2026-11-26). The same on main before ticket 205.

**Where:** `src/sheafmd/edit.py`, the placing of escaped shortcodes (`\:name:`) in changed stretches (`_in_its_gap` and the diff that feeds it).

## Defect

- [x] **A**: when a save holds two changed stretches of about 1 000 words each, and each holds one escaped shortcode (a lone `\:name:`), only one of the two escapes is kept: the other shortcode comes back unescaped and shows as its emoji. Expected: each stretch keeps its own escape. Fix test-first: a test with two such stretches that checks both escapes survive the save.
  Fixed in #691: past the word diff's bound the text is cut at its common start and end and at the words found once on each side, and each stretch is diffed on its own. Test: `tests/test_edit_207.py` (red on main, green on the PR). CI run 45739840750 green on the PR head b2b4851f.

## Notes

- Review of #691: Matt's code review (spec GO; one minor, a chain of cuts charged too little, 0.90 s of CPU, fixed with `_CUT_WEIGHT`, 38 ms; standards minors fixed), Codex b on the branch GO with no findings, the gate's own round an Opus provisional GO.
- Limit, not a regression: a stretch still past the bound with no word found once on each side gives no word matches for the whole text, and every literal falls back to its neighbours.
