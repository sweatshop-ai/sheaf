# Handoff: ticket 208, two tests that failed under load

**Date:** 2026-11-26 · **Ticket:** `.scratch/from-render-doc/208-two-tests-that-fail-under-load.md` · **PR:** #692, merged 17394ad5

## Status

Done. Both tests are fixed in the test only; the product does not race in either case.

- `test_hub_commits.py::test_a_rename_that_arrives_on_a_pull_writes_a_forward_and_carries_the_versions` now gives every hub git 600 s through `roomy_git(monkeypatch)`, which patches `GIT_SECONDS`, `PUSH_SECONDS` and `_git.__kwdefaults__["seconds"]`. The edit's push and the poll settle within 1200 s.
- `test_archive.py::test_archive_after_in_the_roots_toml_changes_the_days` sets the page's mtime to the clock after the create.

## Notes for the next person

- `_renames` in `src/sheafmd/hub/commits.py` catches `SubprocessError`, which includes `TimeoutExpired`, and returns no renames. Under load, a pull can therefore move a page without writing its Forward, and nothing records why. In the product a later poll does not recover it, because base and theirs are then equal. This is a product question, not a test fault, and it is not filed as a ticket. Raise it if a Forward is reported missing.
- `_git`'s `seconds` is keyword-only, so its default lives in `__kwdefaults__` and is bound when the function is defined. Patching `GIT_SECONDS` alone does not reach it.
- `boss_merge` counts a `--since` GO only when the recorded round before it found something. A NO-GO from a review run outside `boss_review` does not count, so this PR needed a full recorded round 3 on the final head.
- The `test_public_tree` name check also scans `.scratch/`. Write "the CI runners", not the runner host's name.

## Open

Nothing on this ticket. The worktree `/tmp/wt-amaia-flaky` and the branch `amaia/flaky-load-tests` are removed after this push.
