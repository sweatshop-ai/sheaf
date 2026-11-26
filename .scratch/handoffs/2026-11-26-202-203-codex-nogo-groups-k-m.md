# Handoff: Codex NO-GO groups K and M, tickets 202 and 203 (2026-11-26)

**Status:** 202 (#684) reviewed GO and merged once its CI on 13e71738 is green, recorded in the ticket. 203 (#687) is open: Codex round 13 gave NO-GO on four serious findings. It goes to a fresh session.

## Ticket 202, group K, PR #684 (from the review of #655)

- **A** `hub/readthrough.py`, `hub/handler.py`: a client page read through an agency hub now gets `proxy: true` and `member` (the signed-in agency member), set by the agency hub, in both the meta block and the mount config. Drafts are therefore namespaced by the agency member, not by fields the client tiroir controls. Tests: `tests/test_read_through_fixes.py`.
- **B** `connect.py`: a peer credential file name longer than 251 bytes (255 minus the `.new` suffix) is cut and ends in `_h` plus a SHA-256 of the origin. Tests: `tests/test_peer_channel.py`.
- Review: Matt's code-review; Codex GO on 96758df0. Each merge of main since (CHANGELOG conflicts) needed a full gate round: fallback GO on 3af02fc5 (round 5) and on 13e71738 (round 6).
- Minors, left open:
  - The PR body names a test as `..._for_every_valid_host_...`; its real name is `..._for_a_long_or_non_ascii_host_...`.
  - CHANGELOG entries cite #684 (correct).

## Ticket 203, group M, PR #687 (from the review of #659), open

Branch `boris/203-group-m`, head b8e1c175, worktree `/tmp/wt-boris-m`.

Done so far:
- **A** `hub/state.py` `_times_out_of_git`: the store's `.gitignore` is written again unless it holds exactly the hub's lines; a nested `.gitignore` between the store and a pin goes.
- **B** `_keep`: the trim in a root's own store counts only pins with a time on this hub.
- **C** `hub/commits.py` `_untrack_pin_times`: tracked `.at` files leave the index, then leave HEAD in a hub commit `versions: pin times out of git` made on a temporary index. It is called before a write's commit and in the sweep, and the commit is owed a push.
  - Round 8 added `state.times_out_of_git(store)`: the store `.gitignore` is set and planted ones are removed before staging.
  - Round 9 refused a `.sheaf` link.
  - Round 10 raised `PermissionError` for a link or another account's store, which keeps the store out of the commit.
  - After CI: the function acts only when the store holds a pin time, which keeps `test_private_root_twin` byte for byte.

Open, Codex round 13 (`~/.claude/pm/reviews/sweatshop-ai/sheaf/pr687/round13.out`), four SERIOUS, to fix test-first:
1. `state.py` `_keep`: a pin shared by two clones becomes trimmable once this clone pins the same hash, so the committed deletion removes the other clone's merge base (409 after restart).
2. `commits.py` `_untrack_pin_times`: any tracked file ending in `.at` is treated as a pin clock. Match `<16 hex>.at` only.
3. `commits.py`: the temp-index `read-tree` and `update-index` bypass `_locking`. A timeout can leave `sheaf-untrack.index.lock`, and every later cleanup then fails on it.
4. `state.py` `times_out_of_git`: the walk unlinks `.gitignore` files in subfolders without checking each folder's owner.

Minors, left open:
- A pin of this hub whose `.at` is garbled or ahead is not trimmed until it is pinned again.
- Tracked `.at` files stay in git when the store is a link or another account's.

Then run one recorded review on the fix diff only (`boss_review.py --since b8e1c17517205f1e06e18fa9e28eb571f1d62795 --track sheaf-backlog`), wait for CI and merge. Every merge of main conflicts on CHANGELOG and then needs a full gate round. The #687 entry sits after "A pin in a root's own versions store keeps its age" so that it does not collide with other tracks' entries.

## Process note

#687 took 13 review rounds. Each fix to C opened a new failure path in the code just added. The code that deals with git's own state (index, HEAD, ignore files) needed its design settled before the first fix.
