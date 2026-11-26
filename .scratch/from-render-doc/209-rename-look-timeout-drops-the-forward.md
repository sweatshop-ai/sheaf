# 209: a rename look that runs out of time drops the Forward

**Claimed by:** Kenji

**Status:** in progress (2026-11-26)

**Blocked by:** none

**From:** the handoff of ticket 208 (`.scratch/handoffs/2026-11-26-208-two-tests-that-fail-under-load.md`), notes for the next person.

**Where:** `src/sheafmd/hub/commits.py`, `_pull` and `_renames`.

`_renames` caught `subprocess.SubprocessError`, which includes `TimeoutExpired`, and returned no renames; a non-zero exit of `git diff -M` gave empty output and so no renames as well. On a loaded machine a pull could then move a page without writing its Forward and without carrying its versions, with no diagnostics row. A later poll does not repair it: base and theirs are then equal.

## Serious

- [ ] **A.** A `git diff -M` that times out or exits non-zero is never "no rename". The pull is held before anything moves (no Write log window opened, no work tree change, the last-seen ref unmoved), a `push-failed` row says why, and the next poll takes the rename in with its Forward and its versions. Red test first, simulating the timeout.
