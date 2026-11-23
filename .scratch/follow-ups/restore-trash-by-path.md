# Restore from the trash still works by path

**What to build:** Make `restore_trash` (`src/sheafmd/hub/archive.py`, lines 275-305 on b96f36bb) move a page back the way `trash` now moves it away (#617, ticket 183 AX): through folder descriptors opened with `O_NOFOLLOW`, never through a path that a link swapped in between the check and the move could redirect.

**Blocked by:** None.

**Status:** open

Today `restore_trash` creates the missing folders of the page's address with a path call, then links the trashed page to its address by path (`os.link(src, dest, follow_symlinks=False)`). AN (#617) closed the race on the trashed entry itself; the folders on the way to the address are still followed. A folder replaced by a link after the containment check sends the restored page outside the root.

- [ ] The folders of the address are created and opened one by one with `O_NOFOLLOW` (`_folder_of`), and the page is linked with `src_dir_fd`/`dst_dir_fd`. DONE WHEN: a test swaps a folder on the address for a link to a folder outside the root between the check and the move, and the restore answers 409 and writes nothing outside the root.
- [ ] Whatever ticket 183 decides for BJ (an in-root folder link) and BL (file systems without hard links) applies to restore too, with the same tests.

**From:** Elke's handoff for #617 (`.scratch/handoffs/2026-11-23-183-core-batch-and-617.md`, after the merge, step 3).
