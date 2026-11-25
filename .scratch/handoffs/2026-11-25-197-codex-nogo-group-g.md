# Handoff: ticket 197, Codex NO-GO group G (edit round-trip), 2026-11-25

**Claimed by:** Yohana. **State:** done, merged in #670 (6a074491).

## Result per original PR

- #631: already fixed by 899a25cf (#634, ticket 183 BX).
- #634: fixed in #670 (197 A, the climb past comments between elements).
- #637: already fixed by 11b72450, merged in 505b328e (#642).
- #642: both findings fixed in #670 (197 B, `data-` attributes read with html.parser's own patterns; no glued names).
- #658: both findings fixed in #670 (197 C, an escaped shortcode in a long change; 197 D, a `<b>`'s own weight).

## Review

One round. Matt's code review: the standards half found the CI runner host named in the ticket (fixed); the spec half found the diff matched A to D. Codex was out of tokens (exit 7), so the Opus fallback reviewed: GO, with one P2 (a `data-` attribute after a lone `/` made the tag self-closing), fixed test first in 137239b0. `boss_review` recorded its own fallback GO, provisional, in `pr670/round01`; its one minor finding (two escaped shortcodes in one changed stretch taking the same place) did not reproduce in three layouts and was rejected.

## Open

- Codex still owes the follow-up review of #670 once its account resets; its findings become tickets.
- Older `strip_data_attrs` cases that differ from the parser and were wrong on main too (a `\x0b` in an attribute name, `<div/ data-x>`): harmless (the block goes through pandoc), no ticket filed.
