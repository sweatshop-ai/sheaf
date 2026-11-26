# Handoff 212: group R of the seventh pass (PR #688 round 3 findings)

**Date:** 2026-11-26 · **PR:** #700, merged as 2d665257 · **Ticket:** `.scratch/from-render-doc/212-codex-nogo-group-r-gone-last-and-take-back.md`

## Outcome

All three serious findings are fixed in #700: A (nothing after `gone` on a stream), B (the take-back cannot delete a file another holds), C (no rename replaces a folder).

## Notes for whoever comes next

- A stream's end is decided at read time, after `accept`. A member stream that refuses `signed-out` must keep going; a first version that ended at put time silenced members after a key rotation (round 1 NO-GO).
- A Linux write lease kills its holder by default when broken (SIGIO): always set `F_SETSIG` before `F_SETLEASE`.
- `boss_merge` wants a recorded round on the live head; a code fix after a GO needs a fix-only round (`--since` the GO head), which counts when the GO had findings and the fix touches only files that round reviewed.
- The minors left open are listed in the ticket.
