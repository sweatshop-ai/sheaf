# Handoff: 183 BW merged in #632 (2026-11-23)

**Status:** done. #632 merged as 3af969df (head 21d4c5a8, CI green). Review: Matt's code-review (standards and spec), its findings fixed in the second commit; then boss_review round 1 (full, on the first head) and round 2 (full, on the rebased head; `--since` is refused across a rebase), both provisional GO with no findings by the Opus fallback. Codex was at its usage limit until 2026-11-24 12:39 UTC, so Codex re-reviews before a deploy.

## What changed (`src/sheafmd/hub/archive.py`, SPEC 8.6)

- A delete refused after the rename has emptied the address (the entry taken from the trash by something outside the hub, or a folder swapped in that cannot be put back) now clears the address's archived, seen and keep marks, so a page made there later is not born archived or kept.
- Each of the three marks is cleared on its own (`_unmark`), on the delete that succeeds too: one mark file that cannot be written no longer keeps the other two. On a refused delete (`_unmark_quietly`) such a failure does not replace the refusal that says where the page went.
- A folder swapped in and put back keeps the marks: the address is not empty.

Tests in `tests/test_trash.py`: the two refused paths and the unwritable mark file (archived, seen), red first; the put-back case pins the other side.

## Open

- **183 BY** (filed, follow-up to 183 BR): marks stay on an address emptied before the delete reached the page (404, or a folder put back). Nothing prunes marks of addresses with no page.

## Cleaned up

The worktree `/tmp/worktree-saskia-183-bw` and the local branch `saskia/183-bw`. The remote branch was deleted at the merge.
