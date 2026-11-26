# 213: pin-time cleanup breaks on a large store and trusts foreign pins; a concurrent render can serve stale settings

**Claimed by:** Kenji

**Status:** in progress

**Blocked by:** none

**From:** Codex re-check pass 8, PR #687 round 16 and PR #679 round 9 (both NO-GO), group S.

**Where:** `src/sheafmd/hub/commits.py` (pin-time cleanup), `src/sheafmd/hub/state.py` (`_pinned_at`), `src/sheafmd/hub/core.py` (first render, `_making`, `moved_remote`).

## Serious

- [ ] **A.** (#687 commits.py:348) Every tracked pin-time path goes on one `update-index`/`ls-tree` command line; a large store passes the argument limit and blocks every hub commit. Red test first.
- [ ] **B.** (#687 commits.py:332) Cleanup removes tracked pin times from git only; a clone that received another clone's `.at` files keeps counting them and can trim its own clocks. Keep the design of C in ticket 203. Red test first.
- [ ] **C.** (#679 core.py:1173) Renders with settings A, B, B at once: the third sees old == new and can serve HTML rendered with A. Red test first.

## Minor

- [ ] **D.** (#679 core.py:615) `_making` is keyed by address only, not root identity.
- [ ] **E.** (#679 core.py:1375) `moved_remote` without `making.detached` leaks a watcher when the first render fails.
