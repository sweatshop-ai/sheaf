# Handoff: #617 merged, 183 items ticked and minors filed (2026-11-23)

**Status:** done. Follows `.scratch/handoffs/2026-11-23-183-core-batch-and-617.md`.

## Done

- #618 (core.py batch: 182 P, R; 183 AM, AO) merged as 2f8620d3, ticked in 25341e51.
- #617 (archive and the moved comment box: 183 AN, AX, AK, X, Y, AP) merged as b96f36bb. Head 82fe828e, CI green, full review round 6 provisional GO (Opus fallback; Codex was at its limit and still has to re-review).
- Ticked in e7005373. The same commit files the open minors from #617's review rounds as 183 BJ to BQ: archive.py BJ to BM, page.js BN to BP, sheaf.js BQ. It also adds a partial-done note to box 1 of `.scratch/follow-ups/comment-box-drag-gaps.md` and opens `.scratch/follow-ups/restore-trash-by-path.md`.
- Cleaned up: the worktree `/tmp/worktree-elke-183`, the branch (local; the remote was deleted at the merge) and `~/vikram-617` on t-compute.

## Fix in #617 worth knowing

On a short page, a box held at the foot was the page's lowest part. When it shrank, the browser clamped the scroll and the box lost its 8 px edge. A margin does not extend the scrollable area (this was measured). `roomBelow()` puts a hidden `.rd-room` spacer, MOVE_EDGE tall, under a held box. The spacer is removed when the box docks or closes, and put back when it undocks. Test: `test_a_box_held_at_the_foot_of_a_short_page_keeps_its_edge_when_the_page_shrinks_again`. page.css is inlined into the page, so a CSS comment must not name `page.js`: `test_render.py` checks for that.

## Open

- 183 BJ to BQ, `restore-trash-by-path.md`, and box 1 of `comment-box-drag-gaps.md` (rotation on the touch fixture, `undock()`).
- Letters BD and BE are used twice: 183 has BD and BE from #619, and 185 also starts at BD. A reference to "BD" or "BE" is ambiguous until one ticket is relettered.
