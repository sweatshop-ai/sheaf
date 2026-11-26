# 203: Codex NO-GO findings on merged PR #659 (group M)

**Claimed by:** Boris

**Status:** in progress

**Blocked by:** none

**From:** the Codex re-check of #659 (ticket 192 fix), round 06, NO-GO. Both findings checked against main; both still hold. Boxes are lettered A and B within this ticket ("203 A").

**Where:** `src/sheafmd/hub/state.py` (`Versions._keep`, a root's own versions store).

## Serious

- [ ] **A** (from #659, `state.py` `_keep`): any `.sheaf/versions/.gitignore` that is a file is trusted: one with other lines, a link to a file, or a `.gitignore` deeper in the store that re-includes `*.at` lets git commit this clone's pin times, so other clones believe pins they did not make and two clones' times conflict. Fix: the store's `.gitignore` is written again unless it is a regular file holding exactly the hub's lines, and a `.gitignore` in a store folder between it and a pin is removed before the pin time is written.
- [ ] **B** (from #659, `state.py` `_keep`): a pin pulled from another clone has no `.at` here, so the trim ranks it at time 0 and deletes its `.md`, a tracked file. The deletion is committed and can take away a merge base the other clone's open page holds (a wrong 409). Fix: in a root's own store the trim counts and deletes only the pins this hub timed; another clone's pins take no slot and are left alone.
