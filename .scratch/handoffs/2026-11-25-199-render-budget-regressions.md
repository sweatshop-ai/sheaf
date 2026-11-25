# Handoff: ticket 199, render time limit regressions (2026-11-25)

**Status:** done. Merged in #673 as 9384b5ff; CI run 45704548289 green. The ticket is ticked: `.scratch/from-render-doc/199-render-budget-regressions.md`.

## What landed

- `_pandoc.budget`, `_deadline`, `_clock` and `_SPENT` are gone: each pandoc run has its own 120 s (G).
- `Hub.render` runs the render, locks included, on a thread named `render <address>` and answers `{doc, url, pending: true}` after `RENDER_ANSWER_WITHIN` (the client's 130 s minus 10). The render goes on and publishes its page (H).
- `sheaf open` on `pending`: no browser, a line on stderr that the next open serves the page, exit 1.
- A failure after `pending` is a `render-failed` row. A failed rebuild for new settings sets `Entry.rebuild_due`, and the next render rebuilds. The warnings of a pending render go to the next open.
- SPEC 3.2 and 15 and the CHANGELOG line of 198 D are updated. 198 F is kept; its docstring gives the new reason.

## Open

- The review was the Opus fallback only (Codex account out until 2026-11-26 00:42): provisional GO, so Codex re-reviews 0f8f77bd before a release.
- A first render still runs pandoc with the hub's lock held (`Hub.entry`). After a `pending` answer, that lock stays held until pandoc ends. This predates #673 and could become a ticket of its own if it shows.
