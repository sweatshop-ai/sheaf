# Handoff: 183 BJ, BK, BL and BM merged in #627 (2026-11-23)

**Status:** done. #627 merged as aa0e5a9b (head 9baa3c58, CI green). Review: Matt's code-review (standards and spec), then boss_review round 1 (full) and round 2 (fix pass since bd8191b5), both provisional GO by the Opus fallback. Codex was at its usage limit until 2026-11-24 12:39 UTC, so Codex re-reviews before a deploy.

## What changed (`src/sheafmd/hub/archive.py`, `handler.py`, SPEC 8.6)

- **183 BJ:** Delete by an address that reaches the page through a folder link inside the root is refused (409), and the answer names the page's own address. The Sheaf never lists such an address, because its walk follows no link.
- **183 BK:** `archive.Gone` is answered 404 for a page or folder that went away between the first look and the move.
- **183 BL, BM:** the move into the trash is a rename again, from `O_NOFOLLOW` folder descriptors, once the trash name is found free under `loose-keep.lock` (a flock every hub process takes). No hard link is needed, and the page is never in two places. A folder swapped in at the page's name is renamed back and refused. A rename ENOENT with the page still at its address means the trash folder went away (409).
- **Restore** keeps its link, so a page put at the address meanwhile is never replaced. Where the file system refuses the link (`NO_HARD_LINKS`), the 409 names the trash entry to move back by hand.

## Known limit (documented in SPEC 8.6)

The free-name check guards against hub processes only. A program outside the hub that writes exactly `.sheaf/trash/<second>/<path>` between the check and the rename would be overwritten. The old link refused that whatever the writer was.

## Open

- **183 BW** (filed): marks are left on an emptied address when the look after the rename fails.
- `.scratch/follow-ups/restore-trash-by-path.md`: restore still follows folders by path, including an in-root folder link. The note under its second box records what 183 decided.

## Cleaned up

The worktree `/tmp/worktree-amara-183-trash` and the local branch `amara/183-trash`. The remote branch was deleted at the merge.
