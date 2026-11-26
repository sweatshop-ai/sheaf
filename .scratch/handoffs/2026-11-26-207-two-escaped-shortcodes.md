# Handoff: ticket 207, two lone escaped shortcodes in two long changed stretches, 2026-11-26

**Claimed by:** Kenji. **State:** done, merged in #691 (57e6f31f).

## Result

- 207 A: fixed in #691. Cause: past `_DIFF_BOUND` (about 1 400 words on each side) `_by_words` gave up on the whole text, so two changed stretches that each fit the bound, but not together, fell back to the literal's 12 neighbouring characters, which had changed. Now a text past the bound is cut at its common start and end and at the words found once on each side (patience anchors), and each stretch is diffed on its own, within a total of `_DIFF_TOTAL` (4 x `_DIFF_BOUND`; a cut charged `_CUT_WEIGHT` per word). Within the bound the single diff is unchanged, so ticket 197's share rule (#658) and #594 behave as before.
- Layout of the test: two stretches of 500 + 500 words around each escape, an unchanged sentence between them, a typed `:smile:` at the end. With 1 000 words on each side of the escape a stretch is 2 000 words and stays past the bound: that case still falls back to the neighbours, as documented in `_places_by_order`.

## Review

One round. Matt's code review: spec GO (box A done, no regression within the bound, pairs monotone); one minor, an adversarial chain of one-anchor cuts spent 0.90 s CPU because a cut was charged too little, fixed with `_CUT_WEIGHT` (38 ms) and a test; standards minors (a `(#207)` citing an unrelated PR, a global `random.seed`) fixed. Codex b on the branch: GO, no findings. Manual round recorded in ~/.claude/pm/reviews/sweatshop-ai/sheaf/pr691/. The gate's own round (boss_review): Opus provisional GO. Merged through `boss_merge`.

CI on the merged head: run 45739840750 green on the PR head b2b4851f (ubuntu py3.13, the one job).

## Open

- Limit, not a regression: a stretch still past the bound with no word found once on each side gives None for the whole text, so every literal falls back to its neighbours.
