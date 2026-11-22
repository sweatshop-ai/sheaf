# CI on the sheaf runners (PR 545): minor findings left out of the PR

**What to build:** Clear the minor findings of review rounds 3 and 4 of PR 545, none of which changes what CI runs today.

**Blocked by:** PR 545 merged.

**Status:** open

- [ ] `tests/test_ci_workflow.py:180` `test_the_organisations_runners_run_sixteen_workers_that_steal_work_and_github_four` is misnamed: it checks `--dist loadgroup`, not work stealing. Rename it.
- [ ] `time.process_time()` in the timing tests (`tests/test_anchoring.py` and the others under the `no_gc` fixture, `tests/conftest.py:130`) counts the CPU of every thread of the worker, not only the code timed. Check whether a thread of a hub left running in the same worker can push a timing past its bound; if it can, time the thread only (`time.thread_time()`).
- [ ] `SPEC.md` (the CI paragraph): "uv's cache and Playwright's browsers are cached; the browsers' key names the runner image ..." is wrong for the sheaf runners, which keep no browser cache (the same paragraph says so a few sentences earlier). Say which runners cache.
- [ ] The job names changed with the move to the sheaf runners. Main has no branch protection and no ruleset, so nothing requires a name today; if one is added, it must name the new jobs.
- [ ] The systemd user-service check (`ci.yml`, step `User service, systemd`) does not run on the sheaf runners (a container has no systemd), so a push to main no longer checks it. Decide whether one GitHub-hosted job keeps it, for example in the nightly run.
- [ ] A manual run with `macos` ticked also slices the ubuntu jobs into six; a manual macOS run needs only its ubuntu twin whole.

Decided, no change: `SHEAF_PUBLIC_TREE_TERMS` is in the environment of the test processes on the persistent runner, readable by a process of the same runner user while a test runs. Accepted: the machine is the owner's own and already holds the private repositories, a fork's pull request runs on GitHub's runners, and only the Tests step gets it.
