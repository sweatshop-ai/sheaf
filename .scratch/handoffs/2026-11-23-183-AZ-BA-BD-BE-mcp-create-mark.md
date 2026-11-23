# Handoff: create's generated mark and the fork's order (183 AZ, BA, BD, BE), merged in #622

**Date:** 2026-11-23. **From:** Kenji. **Boss:** Kaveh (track sheaf-backlog).

## Status

- **PR #622** merged as `cd5fc7cf`; head `fbbe2f10`, CI run 45187927536 green.
- **Review:**
  - Matt's standards and spec reviews: their findings are fixed in `fbbe2f10`. The spec review found the BD race below.
  - `boss_review` round 1 (head `fbbe2f10`): GO, provisional, by the Opus fallback. Codex was at its usage limit until 2026-11-24 12:39 UTC, so Codex re-reviews this head before a deploy.
- **Ticked** on main: 183 AZ, BA, BD and BE, each with its red-first tests (BA has none that can be reached). **Filed:** 183 BR. The worktree and the branch are removed.

## What changed

- **183 BD:** `_make` sets the `generated` mark once the name is found free and before `create_file`, and takes it back if the file is refused. A create with `generated` takes `moves.exclusive()`, as a loose root's create does. Without it, two such creates of one unplaced name by one token in one minute set equal marks, and the loser's `_put_back_mark` cleared the winner's.
- **183 AZ:** `_take_back` undoes a create refused once `_make` is under way: the file, `writes.told`, the folders made at the home (under `folders_lock`), and the mark. `_unmake` reaches each folder through `source._folder_of` with the root's judge, never by path. A first version that removed folders by path deleted an empty list-repo folder through a swapped link; `test_private_folder_swapped_for_a_link_after_the_checks_is_refused` caught it. The list row that `assignees` drops stays dropped.
- **183 BA:** `keep` is set at `page.root` and `page.rel`, where the file was written.
- **183 BE:** `_sessions` runs `_text_writable` before `_writable`, and again inside `change` under the file's lock, before any code check or spend.
- **SPEC:** 7.2 (the fork in the order and lock sentences; create marks before the write) and 12 (Generated pages).

## Open follow-ups (183)

- **BR:** a crash between the mark and the file leaves a mark on an address with no page, which a later create without `generated` inherits.
- **Not done (judgement):** a loose page's folders are still a local list in `_create` beside `_Made.folders`, so `_unmake(top, made, loose_judge)` appears four times. Folding them into one undo record would tidy it.

## Notes

- `place.held` holds nothing for a page the hub does not place; the race tests start the second create from inside a patched `create_file` and `join(1)` it, as `test_two_creates_of_one_name_with_different_homes_make_one_file` does.
- `ruff` reports an unused `loose` (F841) in `mcp.py` `_owned`; it is on main already, and CI runs no ruff.
