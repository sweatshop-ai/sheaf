# Handoff: ticket 198, Codex NO-GOs of group I (2026-11-25)

**Status:** done. PR #669 merged as 24e74512; CI run 45695513902 green, page tests included.

## Per original PR

| PR | Outcome |
|---|---|
| #622 | Already fixed by 8145a941 (ticket 183 BR, #630) and d553fd1e |
| #624 | Serious finding fixed in #669 (198 A); minor (`number_places`) left open as 198 E |
| #628 | Fixed in #669 (198 C) |
| #635 | Fixed in #669 (198 B) |
| #640 | Fixed in #669 (198 D) |

## Review

- Round 1: code review (standards, spec) plus the Opus fallback, because Codex account b was out of tokens until 2026-11-26 00:42. GO. The minor findings were fixed in 947749eb, including 198 F: a failed pandoc reading of a table block is no longer cached.
- Round 2: recorded by boss_review, provisional Opus GO.
- Codex should re-check #669 once it is back.

## Open

- **198 G and H, the cost of D.** A render that waits behind a long save, or a page whose pandoc runs together exceed 120 s, now fails instead of finishing after `sheaf open` gave up. Decision needed: start the budget after the locks are taken, or accept this.
- **198 E:** test helper key width, reason in the ticket.
