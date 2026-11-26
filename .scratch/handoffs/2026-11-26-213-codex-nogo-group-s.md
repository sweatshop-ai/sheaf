# Handoff: ticket 213, Codex NO-GO group S (2026-11-26)

## Status

Done. PR #701 merged as a0895c69. Ticket: `.scratch/from-render-doc/213-codex-nogo-group-s-pin-times-and-stale-render.md` (boxes A to E ticked, with evidence).

## Per original PR

- **#687 round 16**: both serious findings fixed in #701 (A: pin-time paths on stdin; B: pin times carry this hub's mark for the store, a foreign time is neither believed nor counted).
- **#679 round 9**: the serious finding fixed in #701 (C: settings numbering, a render never answers with a page of older settings); minors D and E fixed in the same PR.

## Reviews

- Matt's code review: standards, no hard violation (minors applied); spec, GO.
- Codex b out of tokens (exit 7). Gate rounds by the Opus fallback: 01 GO on 099fd8d8, 02 GO on the fix diff 1b855f64. The SPEC wording minor of round 02 is fixed on main in the tick commit.
- Pending: one Codex check on #701 once Codex b is back; its findings become tickets.

## Known limits

- Pin times written before #701 carry no mark: not believed until the page pins again.
- A root's folder moved or renamed: its pin times are not believed until pinned again.
- Tickets 210 and 212 gained a "Known limits (Codex recheck pass 8)" section for #695 r04 and #700 r04, under the stop criterion of 2026-11-26.

## Next

Nothing in group S. The branch `kenji/213-group-s` was merged and deleted by the gate.
