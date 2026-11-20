# The trash listing follows a linked trash folder

**What to build:** `Archive.trashed` (and the restore that reads the same folders) refuses a linked `.sheaf` or `.sheaf/trash`, as `trash` and `purge` do.

**Blocked by:** None.

**Status:** open

## Problem

`src/sheafmd/hub/archive.py` `trashed` scandirs `<root>/.sheaf/trash` and walks each stamp folder with `os.scandir`/`os.walk` without the `_plain_dir` check that `trash` makes and that `purge` makes since the follow-up to finding 158 of the Opus re-check. A `.sheaf` or `.sheaf/trash` that is a link to another folder is followed, so the trash view lists digit-named folders and files of the link's target, and `restore_trash` can link one of them into the root. Planting the link needs the owner's own hand on the member's loose root, as for finding 158.

## DONE WHEN

- [ ] A test plants a link in place of `.sheaf` (and one in place of `.sheaf/trash`) in a loose root, puts a digit-named folder with a page in the target, and asserts `trashed` lists nothing and `restore_trash` of that id is refused or not found.
- [ ] `trashed` calls `_plain_dir` on `.sheaf` and on the trash folder first, and returns `[]` where it raises.
- [ ] `restore_trash` makes the same check before it reads `src`.
- [ ] A normal trash (no link) lists and restores as before: `tests/test_trash.py` green.
