# Handoff: ticket 186 merged (#636); 186 done

**Date:** 2026-11-23
**Merged:** #636 as c478ed4f; head 2167a791, CI green (ubuntu-24.04 py3.13; the first attempt lost its self-hosted runner in the Playwright step and was rerun).
**Review:** Matt's code-review (Standards: no hard violations; Spec: GO), then boss_review round 1 (full) and round 2 (fix-only, `--since 1d2d48a8`), both provisional GO by the fallback reviewer (Codex at its usage limit). Codex re-reviews 2167a791 before a deploy.

## What changed

- `src/sheafmd/hub/peer.py`:
  - `_owners` keeps one `Socket` per (uid, inode), in the order first seen. Inode 0 rows stay as listed.
  - `_proc_owners` reads tcp and tcp6 once more when neither lists the socket (`_PROC_READS = 2`).
  - `_selftest` compares the set of uids, as `check` does.
- `tests/test_hub_peer.py`: tables that list the row twice or skip it, each red on main except the guards (two uids on one inode, inode 0, no re-read after a find, no re-read of an unreadable table).
- `tests/test_hub_peer_lookup.py`: the self-test on `[ME, ME]` (red on main) and a two-second churn test over the real /proc (green on main too; a regression guard).

## Notes

- A churn test that closes its sockets normally leaves thousands of TIME_WAIT rows for a minute, and every later test that reads /proc/net/tcp slows with them (one gate test took 68 s instead of 0.04 s). Close churn sockets with SO_LINGER 0.
- Not covered: a row skipped inside a non-empty answer (another row of the same inode with another uid). One inode cannot carry two uids, so this is no regression from main.
