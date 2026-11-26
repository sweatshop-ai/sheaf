# 212: gone is not the last event for a stale entry; the take-back can still lose an editor's write

**Claimed by:** Anouk

**Status:** done (2026-11-26), PR #700 merged as 2d665257

**Blocked by:** none

**From:** Codex re-check of PR #688, round 3 (NO-GO), group R of the boss's seventh pass.

**Where:** `src/sheafmd/hub/live.py` (`_tell_grants` and other hub paths publishing on an `Entry`), `src/sheafmd/mcp.py` (take-back of a refused create).

## Serious

- [x] **A.** The forgotten gate covers only `LiveDocument` publications. `_tell_grants` holds a stale `Entry` and calls `e.bus.publish(...)` directly; a delete can publish `gone` before that publish, so `gone` is not the stream's last event. Red test first.
- [x] **B.** The take-back checks the file with `fstat`, then unlinks it. An editor holding an open descriptor can write between the two (and a same-size write can pass a coarse mtime), and the unlink deletes that write. The take-back must not be able to delete data: keep the file aside rather than delete it when a late write cannot be ruled out. Red test first.
- [x] **C.** The directory fallback uses a plain `rename`, which on POSIX replaces an empty directory that arrived at the path. Nothing may be replaced: `renameat2(RENAME_NOREPLACE)` or an equivalent. Red test first.

## Evidence

- **A.** A stream ends on the end event it is sent, decided in `Subscription.get` after `accept`; nothing is given after it, whoever publishes. Tests: `test_hub_events_bus.py` (`..._hears_nothing_after_its_last_event_whoever_publishes`, `..._refuses_does_not_end_it`, `..._sent_in_place_of_another_ends_it`), `test_hub_listing.py` (`..._nothing_after_gone_through_an_entry_held_from_before`).
- **B.** The take-back deletes only under a Linux write lease (break signalled with SIGURG, not SIGIO), with the mode taken to none before the last look and a file with a second name never deleted; where no lease is granted the file is kept aside and named. Tests in `test_hub_place.py`, among them the subprocess tests for a lease broken during the look and an open right before the delete.
- **C.** The folder fallback uses `renameat2(RENAME_NOREPLACE)` / `renamex_np(RENAME_EXCL)`: nothing is replaced. Tests: `..._never_renamed_over_an_empty_folder_that_came_to_its_name`, `..._goes_back_to_its_name_when_nothing_came`.
- Reviews: recorded rounds 1 (NO-GO), 2 (GO, fix diff), 3 (GO, fix diff); Codex on the fix commits of rounds 1 and 2. CI green on 5422b8cd (run 45769870925).

## Left open (minor, documented in the code)

- A hard link made after the link-count check, or an open already past its permission check as the mode changed, is not kept out.
- Any other holder, the hub's own reader included, refuses the lease: the file then goes back to its name, without its mark.
- A hub that dies between the mode change and the delete leaves the hidden file at mode none.

## Known limits (Codex recheck pass 8)

Recorded, no new PR: the stop criterion of 2026-11-26 fixes only defects reachable in normal use, or that lose data without a constructed race.

- #700 round 04:
  > FINDING: [SERIOUS] `src/sheafmd/mcp.py:1689` — `_lease_held()` is only a snapshot. An `open()` already past the new mode check can begin breaking the lease immediately afterward; rollback then unlinks and closes the file, allowing the blocked opener to resume with an unlinked descriptor whose writes are lost. Linux performs the lease break late in the [open path](https://github.com/torvalds/linux/blob/master/fs/open.c).
- #700 round 04:
  > FINDING: [SERIOUS] `src/sheafmd/mcp.py:1684` — The lease does not protect namespace operations. Between the link-count check and pathname unlink, another process can hard-link the inode, leaving that link mode `000`, or rename the sibling and replace it, causing rollback to unlink the replacement. Leases mediate only `open` and `truncate`, per [Linux lease semantics](https://www.man7.org/linux/man-pages/man2/F_SETLEASE.2const.html).
