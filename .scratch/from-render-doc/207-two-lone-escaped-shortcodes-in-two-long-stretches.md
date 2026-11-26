# 207: two lone escaped shortcodes in two long changed stretches keep only one escape

**Claimed by:** Kenji (filed only, no fix in this ticket)

**Status:** open

**Blocked by:** none

**From:** found while working on ticket 205 (see its handoff, 2026-11-26). The same on main before ticket 205.

**Where:** `src/sheafmd/edit.py`, the placing of escaped shortcodes (`\:name:`) in changed stretches (`_in_its_gap` and the diff that feeds it).

## Defect

- [ ] **A**: when a save holds two changed stretches of about 1 000 words each, and each holds one escaped shortcode (a lone `\:name:`), only one of the two escapes is kept: the other shortcode comes back unescaped and shows as its emoji. Expected: each stretch keeps its own escape. Fix test-first: a test with two such stretches that checks both escapes survive the save.
