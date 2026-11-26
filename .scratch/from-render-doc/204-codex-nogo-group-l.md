# 203: Codex NO-GO findings on merged PR #662 (group L)

**Claimed by:** Amaia

**Status:** in progress

**Blocked by:** none

**From:** the Codex re-check of #662, round 03, NO-GO with three serious findings. All three checked against main a767a45b: all three still hold. Boxes are lettered A to C within this ticket ("203 A").

**Where:** `src/sheafmd/mcp.py` (`_take_back`), `src/sheafmd/hub/core.py` (`forget_document`), `src/sheafmd/hub/live.py` (`_rerender_settled`).

## Serious

- [ ] **A** (from #662, `mcp.py` `_take_back`): the take-back of a refused create compares the file's inode with the one it made and then unlinks the name. A file put at the name between the look and the unlink is deleted, and an editor that saves in place keeps the inode, so its text is deleted too. Fix: the file is first renamed aside (atomic: the rename takes one inode), and only a file that is the one made, with the text written, is deleted; any other is linked back at its name, or kept aside and said when the name has been taken meanwhile.
- [ ] **B** (from #662, `hub/core.py` `forget_document`): a page deleted into the trash tells its tabs `gone` without marking its live document forgotten, so a render that had already taken the entry can publish `changed` after `gone`, which must be the stream's last event (SPEC 8.8). Fix: the document is marked forgotten under its own lock before `gone` goes out, as `forget_root` does, without dropping its versions; and nothing a forgotten document does is published.
- [ ] **C** (from #662, `hub/live.py` `_rerender_settled`): a refresh or rebuild that finds its read torn renders the page again from the text the tabs hold, but the torn render has already replaced the page the hub serves. When that second render fails, the torn page is served while the document's text and hash are the kept ones. Fix: the page served before the torn render is put back when the second render fails.
