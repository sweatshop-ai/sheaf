# 204: Codex NO-GO findings on merged PR #662 (group L)

**Claimed by:** Amaia

**Status:** done (PR #688, merged 60f4a683)

**Blocked by:** none

**From:** the Codex re-check of #662, round 03, NO-GO with three serious findings. All three checked against main a767a45b: all three still hold. Boxes are lettered A to C within this ticket ("204 A").

**Where:** `src/sheafmd/mcp.py` (`_take_back`), `src/sheafmd/hub/core.py` (`forget_document`), `src/sheafmd/hub/live.py` (`_rerender_settled`).

## Serious

- [x] **A** (from #662, `mcp.py` `_take_back`): the take-back of a refused create compares the file's inode with the one it made and then unlinks the name. A file put at the name between the look and the unlink is deleted, and an editor that saves in place keeps the inode, so its text is deleted too. Fix: the file is first renamed aside (atomic: the rename takes one inode), and only a file that is the one made, with the text written, is deleted; any other is linked back at its name, or kept aside and said when the name has been taken meanwhile.
- [x] **B** (from #662, `hub/core.py` `forget_document`): a page deleted into the trash tells its tabs `gone` without marking its live document forgotten, so a render that had already taken the entry can publish `changed` after `gone`, which must be the stream's last event (SPEC 8.8). Fix: the document is marked forgotten under its own lock before `gone` goes out, as `forget_root` does, without dropping its versions.
- [x] **C** (from #662, `hub/live.py` `_rerender_settled`): a refresh or rebuild that finds its read torn renders the page again from the text the tabs hold, but the torn render has already replaced the page the hub serves. When that second render fails, the torn page is served while the document's text and hash are the kept ones. Fix: the page served before the torn render is put back when the second render fails.

## Evidence

- PR #688, merged 60f4a683 through boss_merge on bb1ddc37 (round 2, provisional Opus GO: Codex at its usage limit). CI run 45739610898 green on that head.
- **A:** `_take_back_file` renames the name aside, deletes only the made inode with the written bytes (looked at again right before the delete, so a write through a held descriptor keeps the file), and links any other file back with `os.link` (never overwrites); a name taken meanwhile leaves the file aside, named in a `take-back-left-file` row. Tests in `tests/test_hub_place.py` (editor saving in place, file put at the name after the look, write through an open descriptor during the look, file kept aside and named), each red on the old code.
- **B:** `forget_document` calls `LiveDocument.close()` (marks it forgotten under its lock) before `gone`; every event, tells included, goes through the `_forgotten` gate. Tests: `test_hub_listing.py::test_a_page_deleted_while_a_render_of_it_runs_tells_its_tabs_gone_last`, `test_hub_live.py::test_a_closed_document_tells_its_tabs_nothing_after_gone`.
- **C:** `_rerender_settled` keeps the served page (`keep_page`: html, log, first, images_scope) before the torn render and puts it back when the second render fails. Tests: `test_hub_live.py::test_a_torn_read_whose_second_render_fails_serves_the_page_the_tabs_hold[refresh,rebuild]`, `test_hub_listing.py::test_a_torn_read_whose_second_render_fails_leaves_the_hub_serving_the_page_it_served`.
- Residual, documented in `_delete_if_made`: a write through a held descriptor between the last look and the unlink is not seen.
