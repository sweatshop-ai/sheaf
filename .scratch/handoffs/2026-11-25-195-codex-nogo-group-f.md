# Handoff: ticket 195, Codex NO-GO group F (2026-11-25)

**Done.** PR #662 merged in ecc7241a. Ticket: `.scratch/from-render-doc/195-codex-nogo-group-f.md`.

## Per original PR

- #611: all three findings already fixed by 6da3d378 (#626).
- #615: already fixed by 608f945a (#621, 183 BB).
- #616: the mark-before-file finding fixed by 7d6e44c9 (#622, 183 BD); its PathError remnant (195 D) and the take-back that deleted a replacement file (195 E) fixed in #662.
- #617: archive findings fixed by 0f3d816b (#627); page.js and sheaf.js findings fixed by 1cbf75f3 and 09eb60d4 (#628).
- #618: all three findings (195 A, B, C) fixed in #662.

## Left open (minor, in the ticket)

- F: `Hub.forget_document` publishes `gone` without `live.forget()`.
- G: a failing second render in `_rerender_settled` leaves the torn page served until the next refresh.
- H: repeated generated-mark seeding line in four tests.

## Notes

- Codex was out of tokens; the review round is the Opus fallback recorded by boss_review (round01, provisional GO). Codex owes a follow-up recheck of #662 once back.
- GitHub's merge endpoint failed for #662 (GraphQL error three times, REST 502). The merge commit was made by hand; GitHub had not yet marked the PR merged when this was written.
