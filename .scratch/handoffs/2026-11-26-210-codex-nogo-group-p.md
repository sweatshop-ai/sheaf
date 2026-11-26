# Handoff: ticket 210, Codex NO-GO group P (edit.py hard-break runs and escaped shortcodes), 2026-11-26

**Claimed by:** Imani. **State:** done, merged in #695 (9903db92).

## Result per original PR

- #685, round 06 (a new run with two partial lines outranked the source run with one unchanged line): fixed in #695 (210 A).
- #691, round 02 (a partial word match skipped the neighbour fallback for an escaped shortcode): fixed in #695 (210 B).

## Review

Matt's code review: on standards, naming minors only (applied). On spec, the first version of B sent every unmatched literal to its neighbours, so an escape the reader deleted went to a `:smile:` typed after the same 12 characters. Fixed test first. Codex b gave P2s only. The gate's round 01 was an Opus fallback GO. Round 02, a full round after a rebase broke `--since`, was NO-GO on the same regression in a cut diff. The fix, test first: an unmatched literal is probed on a side only when the word beside it there is unmatched too, meaning it moved. Round 03 (fix pass) was GO. Merged through `boss_merge`.

CI on the PR head: run 45762958928 green (ubuntu py3.13, the one job) on d08e9b95.

## Open

- 210 B2, B3, B4 and A2 (all minor, reasons in the ticket). B3 is inherent: a deleted phrase retyped elsewhere is the same text as a move.

## Notes for the next person

- `boss_review.py --since` needs the head of a recorded round. A rebase after a round rewrites that head, and a fix pass then has nothing to read from. Push the fix commits on top, and rebase only when merging needs it.
