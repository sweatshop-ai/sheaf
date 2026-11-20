# 155: Real names and a private host name are back in the public tree, and nothing checks for them

**Claimed by:** Felix 2026-11-20 15:56

**Status:** done (already delivered by #445, merged 2026-11-17; nothing left to change)

**Blocked by:** none

**From:** render-doc ticket 155 (private archive), triaged 2026-11-12

**Where (main 81afdff):** mostly test fixtures; also `SPEC.md:887`, `:995-996`, `:1026`, `:1070-1071`, `:1229`, `docs/design/2026-11-07-agents-and-waiting-tells.md` (lines 3 and 12 among others), `src/sheafmd/agent_setup.py:270`

**Size:** one mechanical rename plus one test; the deny list itself comes from the owner and stays out of the repo

The audit this ticket tracked removed every private name from the tree before the fork into this repo, and all of the leaks it listed are still gone. But new ones came in after the fork, and the check script that guarded the tree did not move here.

- [x] **Real first names of the team, the company name and a private hostname are in the tree again**, mostly as test fixtures (members, owners, projects, hosts) and in a few SPEC examples. A count on main with `git grep -i -w -c` over `src`, `tests`, `SPEC.md`, `README.md`, `docs` and `tools` found several hundred lines in all:
  - test fixtures, biggest files first: `tests/test_hub_place.py`, `tests/test_hub_visibility.py`, `tests/test_hub_work.py`, `tests/test_hub_grants.py`, `tests/test_hub_member_dirs.py`, `tests/test_hub_relay.py`; a second private host name in `tests/page/test_mount_selection.py` and `tests/page/test_mount_allowlist.py`;
  - SPEC examples: `SPEC.md:887`, `:995-996`, `:1026`, `:1070-1071`, and the "seen by ... in trial 2" note at `:1229` (ticket 96 names the three SPEC lines with the owner's name);
  - the design note `docs/design/2026-11-07-agents-and-waiting-tells.md`.

  Look: `git grep -n -i -w -E '<names>' -- src tests SPEC.md README.md docs tools`, with the list from the owner. Fix: rename to invented names (some tests already use invented people and companies) and use `example-box` for a host. Then add a test that reads a private deny list from outside the repo (a path in an environment variable) and fails on any hit, skipped when the list is absent, so the owner's machine and a private CI catch a regression without the list ever being published.

- [x] **Smaller residue (judgement):** `src/sheafmd/agent_setup.py:270` still names "codex-cli 0.147.0" in a docstring; the audit asked for the version log to go and the check to stay.

## Outcome (Felix, 2026-11-20)

Item 1 was delivered by PR #445 (`tests/public_tree.py`, merged 2026-11-17): the names are in the repository secret `SHEAF_PUBLIC_TREE_TERMS` (set 2026-11-17T15:42Z, `gh secret list`), not in the tree, not as hashes (a hash of a short name is recoverable). The tree was cleaned before it merged. Evidence: #445 is an ancestor of main `b761a062`; the CI run on main after it has all 6 test slices `success`, the guard running in the Tests step; `git grep` over the tree for the owner's and team's names finds only the owner's first name in `.scratch/` ticket text and nothing in `src`, `tests`, `SPEC.md`, `docs`.
Item 2, judgement: `agent_setup.py:270` and `tests/test_init.py:747,806` name `codex-cli 0.147.0` as the observed version a test's fixture comes from. It is a public tool's version, not a private fact, and it documents why the fixture has that shape; kept.
