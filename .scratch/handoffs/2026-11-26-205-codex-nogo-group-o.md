# Handoff: ticket 205, Codex NO-GO group O (edit.py data attributes and escaped shortcodes), 2026-11-26

**Claimed by:** Alonso. **State:** done, merged in #689 (c9e928fb).

## Result per original PR

- #670, finding 1 (`strip_data_attrs("<div/data-x>")` gave `<div/>`, a tag that closes itself): fixed in #689 (205 A).
- #670, finding 2 (`_in_its_gap` gave two escaped shortcodes the same `:name:`): fixed in #689 (205 B).

## Review

One round. Matt's code review: the standards half gave style points (applied); the spec half found the first fix also stripped the `/` a bare value ends in (fixed, test first) and the placement left open as B2. Codex b gave no verdict, so the Opus fallback reviewed: GO with two minors (the same `/`, and a test case that never dropped an attribute), fixed in 2ce8b83e; GO on that diff only (round 02). Merged through `boss_merge`.

CI on the merged head: 11337 passed, one failure, `test_land_root`, which fails on main until #677 lands.

## Open

- 205 B2 (minor): in the finding's own layout the two escapes go to the second and third `:s:`, by ticket 197's share rule; both are kept, no text is lost.
- Not filed, the same on main before this ticket: two lone escaped shortcodes in two changed stretches of about 1 000 words each keep only one escape.
