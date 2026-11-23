# Handoff: handler.py batch (182 G, O; 183 AL, AT, AV), merged in #619

**Date:** 2026-11-23. **From:** Kenji. **Boss:** Kaveh (track sheaf-backlog).

## Status

- **PR #619** merged as `e17558dc`; head `b4741371`, CI run 45176597261 green.
- **Review:**
  - Matt's standards and spec reviews: their findings are fixed in `6922ca7a`.
  - `boss_review` round 1 (head `6922ca7a`) and the fix pass, round 2 (`--since 6922ca7a`, head `b4741371`): both GO, provisional, by the Opus fallback. Codex was at its usage limit until 2026-11-24 12:39 UTC, so Codex re-reviews this head before a deploy.
- **Ticked** on main: 182 G and O, 183 AL, AT and AV, each with its red-first tests. The worktree and the branch are removed.

## What changed

- **G:** the save guard (`_ticks`) and the share's `change` call `_text_writable` again under the file's lock. In the guard it comes right after the 404 for a reader who may not open the page, before the front-matter, one-off and Share refusals; in the share, before the owner check.
- **O:** the guard's `elif` tests `visibility.audience(new) is not None`, so a renamed-and-ticked `Share with <names>` is unticked like a plain Share.
- **AL:** `_with_team` sends a non-object meta block, or a mount `config` that is not an object, on as it came.
- **AT:** `_split_unquoted` cuts `Accept` outside quoted strings.
- **AV:** `_text_writable` before `_writable` at save, tick and share.
- **Tests:** `tests/helpers.py` gains `mark_generated` and `marked_after_the_look`. The second puts the mark into `docs.json` right after the first look, which is how the G race is made reproducible.
- **SPEC:** 7.2, 9.11 and the `/_/open` row.

## Open follow-ups (183)

- **BD:** a door `create` with `generated` sets the mark after `_make` wrote the file, outside the file lock for a page the hub does not place (`mcp.py`).
- **BE:** `POST /_/sessions` keeps the read-only-before-generated order and does not look at the mark again under the file lock.

## Notes

- `place.held` holds nothing for a page the hub does not place (`place.py`). A test that hooks `place.held` to set the mark fires before the first look, so it does not reproduce the race.
- The ordering in the guard has no reachable test for the front-matter case: a page save writes `---` as `\---` (ticket 137), so a save cannot change the front matter.
