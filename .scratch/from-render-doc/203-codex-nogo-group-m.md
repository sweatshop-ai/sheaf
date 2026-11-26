# 203: Codex NO-GO findings on merged PR #659 (group M)

**Claimed by:** Boris, then Stellan

**Status:** done: #687 merged as 20854dbb on head 6b24e98c (CI run 45764342412 green; recorded rounds 14 and 15, provisional GO from the fallback review)

**Blocked by:** none

**From:** the Codex re-check of #659 (ticket 192 fix), round 06, NO-GO. Both findings checked against main; both still hold. Boxes are lettered A and B within this ticket ("203 A").

**Where:** `src/sheafmd/hub/state.py` (`Versions._keep`, a root's own versions store).

## Serious

- [x] **A** (from #659, `state.py` `_keep`): any `.sheaf/versions/.gitignore` that is a file is trusted: one with other lines, a link to a file, or a `.gitignore` deeper in the store that re-includes `*.at` lets git commit this clone's pin times, so other clones believe pins they did not make and two clones' times conflict. Fix: the store's `.gitignore` is written again unless it is a regular file holding exactly the hub's lines, and a `.gitignore` in a store folder between it and a pin is removed before the pin time is written.
- [x] **B** (from #659, `state.py` `_keep`): a pin pulled from another clone has no `.at` here, so the trim ranks it at time 0 and deletes its `.md`, a tracked file. The deletion is committed and can take away a merge base the other clone's open page holds (a wrong 409). Fix: in a root's own store the trim counts and deletes only the pins this hub timed; another clone's pins take no slot and are left alone.
- [x] **C** (from the Codex review of #687, `commits.py`): a `.gitignore` hides only untracked files, so a pin time git took in before A (an older hub, a planted `.gitignore`) goes on being committed. Fix: before any commit of the store (a write's, the sweep's), under the repo's lock, every tracked `<hash>.at` of the store leaves HEAD in a hub commit of its own (`versions: pin times out of git`, made on an index of the hub's own, since `commit -- paths` takes a tracked file back from the work tree) and leaves the index; the file stays on disk. The commit is owed a push, and the write's or sweep's own commit starts from it (Codex round 2 on #687). Redesigned after round 13 (design note below): the cleanup changes git's index and HEAD only, matches `<16 hex>.at` in a pins folder only (`state.is_pin_time`), builds its HEAD commit on an index in a fresh temporary folder, and no hub commit carries a pin time; the trim of a root's own store drops this hub's time, never a pin text. Tests: `tests/test_hub_state.py`, `tests/test_hub_commits.py`.

## Minor, left open

- A pin of this hub whose `.at` is garbled or more than a minute ahead is not believed or counted until it is pinned again. Since round 13 the trim deletes no pin text in a root's own store, so nothing is lost meanwhile.
- The two open limits of the design note below.
- A refusal to take a staged pin time back out of the index fails that write's commit whole, document included, until the next write; a refusal in the cleanup before it commits the document alone (spec review of #687).
- SPEC 7.4 does not name the second open limit (an untracked pin time in `git status`).

## Design of C, after Codex round 13 on #687 (2026-11-26)

Thirteen rounds patched C one failure at a time. This note fixes the rules first; the four round-13 findings follow from them.

### Definitions

- **Pin time**: a path, relative to the root, that matches `.sheaf/versions/<16 hex>/pins/<16 hex>.at` or `.sheaf/versions/<16 hex>/pins/m-<16 hex>/<16 hex>.at`. Nothing else is one: `notes.at`, `pins/x.at` or `.sheaf/versions/a.at` are files of the root like any other. One test, `state.is_pin_time(rel)`, used by every caller.
- **Pin text**: `<16 hex>.md` in a `pins` folder.

### Rules

1. **The trim of a root's own store takes away this hub's clock, never the pin text** (finding 1). A pin text git carries may be pinned by another clone too, and nothing on this clone says so: a clock is local by design. Deleting the text, committed and pulled, takes the other clone's merge base away. So no hub deletes a pin text from a root's own store; the trim removes `<hash>.at` only, and the pin is no longer believed or counted here. The state folder's store is unchanged.
2. **The commit-side cleanup touches git's index and HEAD only, never the work tree** (finding 4). It writes and removes no `.gitignore` and no other file, so the owner of a folder, a link, or another account's directory cannot matter to it. `times_out_of_git` and its walk go. The store's `.gitignore` is still set when a pin is written (A), in folders `inside_dir` has checked.
3. **No commit of the hub carries a pin clock, whatever the ignore files say.** After `add`, every staged pin clock under the commit's paths leaves the index before `commit -- paths` (which takes no untracked file); the sweep drops pin clocks from its lists by name. A missing, linked or rewritten store `.gitignore`, or a planted `!*.at`, cannot let one in.
4. **HEAD's pin clocks leave in a commit made on an index in a fresh temporary directory**, which is removed whole, index and any `.lock`, whatever happens (finding 3). No name is reused, so a git killed on its bound never blocks a later run. The real index is changed only through `_locking`.
5. **Only pin clocks leave git** (finding 2): a tracked `.at` that does not match the shape is never removed.

### States the cleanup can meet

| State | What the cleanup does |
|---|---|
| No store, or an unborn HEAD | Nothing; with an unborn HEAD only the index step runs |
| `.sheaf` or the store is a link | git lists no path beyond a link, so no pin clock matches: nothing |
| A store folder of another account | Same as any folder: only git's index and HEAD change, no file is touched |
| Store `.gitignore` missing, linked, other lines, or a `!*.at` below | No effect on the hub's commits (rule 3). Untracked clocks can show in a person's `git status` until a pin writes the store `.gitignore` |
| A tracked `.at` that is no pin clock | Left in git (rule 5) |
| A pin clock in the index only (a person's `git add -f`) | Leaves the index under `_locking`; no commit |
| A pin clock in HEAD | Leaves the index, then HEAD in `versions: pin times out of git` on a temporary index; owed a push |
| The repo's `index.lock` held (a live or stale git of the person) | `_locking` fails on it: error, the store is not staged, the document is committed alone. A stale lock of the person's is never the hub's to remove (#38) |
| A git killed during the HEAD step | The temporary directory goes with its index and lock; HEAD is unchanged; the next run starts afresh |
| HEAD moved between the read and `update-ref` | `update-ref` with the old value refuses: error, retried at the next commit or sweep |
| A pin shared by two clones | Each trims only its own clock; the text stays for both (rule 1) |
| A pin of another clone, with no clock here | Not believed, counted or deleted (B) |

### Open limits

- Pin texts in a root's own store are never deleted by the hub: they accumulate, one file per version pinned, until a person removes them. A safe deletion needs to know that no other clone pins the text, which no local state says.
- After a pin clock leaves git, it shows as untracked in `git status` until this hub pins in that store (which writes the store `.gitignore`).
