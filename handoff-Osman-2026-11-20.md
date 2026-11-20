# Handoff: Osman, ticket 91 wrap-up and CI on the organisation's runners, 2026-11-20

Boss: Kenji (track sheaf-backlog). Rules: `/home/tiroir/.claude/pm/sheaf-backlog.dispatch-rules.md`, wave file `/home/tiroir/.claude/pm/sheaf-backlog.wave-2026-11-20.md`.

## Ticket 91 (taken over from Amir)

| PR | Item | Head | Round | Exit | Status |
|---|---|---|---|---|---|
| 485 | 1, brand rule | b0e2ed89 | 1 | 0 | merged 82de3806 |
| 487 | 2, cancel | 5f081ad5 | 1 | 0 | merged 7aff3530 |
| 496 | 3, render rebuild off the hub lock | c8d79511 | 1 | 0 | merged e5f10c6f |
| 491 | 3, forget off the hub lock | b7932be1 (rebased on main after 496) | 2 | 0 | OPEN, not merged |

- Boxes 1 and 2 of `.scratch/from-render-doc/91-roots-follow-ups.md` are ticked with evidence (commit 9ef74e1c on main). Box 3 is open until 491 merges.
- 491: CI on b7932be1 has slices 1, 2, 3, 5, 6 green. Slice 4 was red on infra only ("the browsers did not install in three tries" after 1682 passed). It was rerun under the owner's standing permission (infra failures of a worker's own PR only, never a red test): run 44789430505, still queued in GitHub's backlog at the last look. Kenji merges 491 once it is green.
- After 491 merges: tick box 3 with evidence; add under item 3 that `loose.drop` calling `forget_root` under `loose.lock` can wait on a render (known, not new, Kenji 2026-11-20) and that `rebuild` can still run on an entry `forget_root` just took (a `changed` after `gone`, cosmetic, seen in the 496 review); remove the worktrees `/home/tiroir/Projects/sheaf-wt-amir`, `sheaf-wt-amir3`, `sheaf-wt-amir4` and their branches.

## CI on the organisation's runners: PR 545 (draft)

Goal (owner's choice): an ubuntu job of this repo runs on the organisation's own runners, one job per Python, `pytest -n 16 --dist worksteal`; fork PRs and macOS stay on GitHub's.

- Worktree `/home/tiroir/Projects/sheaf-wt-osman`, branch `osman/ci-on-t-compute`, head 16fa09a7, round 1 GO on 40bab20f (the later commits only renamed the label and removed the host name). It is stacked on Rania's #533 (6cacb8fb, unmerged): two of its commits are in the branch. It was 59 commits behind main at the last look, so rebase it on `origin/main` and push, then re-run the recorded round (`boss_review.py --pr 545 --checkout <worktree> --author Osman --track sheaf-backlog`; a full round if the base moved).
- Design in the workflow: `runs-on` is `[self-hosted, linux, sheaf-ci]` when the matrix os is ubuntu and the event is not a fork PR; the slice list is empty on those runs (the whole suite), six slices for a fork PR or a manual run with macOS. On a self-hosted job `--with-deps`, the user-service checks, the browser cache and the image-name step do not run, the checkout has `persist-credentials: false`. Five timing tests read `process_time` under a new `no_gc` fixture. SPEC 18 and `tests/test_ci_workflow.py` agree.
- Security: a fork PR reads the fork's own workflow file, so the `runs-on` expression is not the guard. The guards are fork-PR approval `all_external_contributors` (set by the owner) and a reviewer reading the `.github/workflows/` diff before approving. `restricted_to_workflows` was left out: the docs do not say which ref is compared for a PR run, so it could block our own PR runs.
- Owner part, done by the owner: runner group `sheaf-public` (id 3, selected, public repos allowed, only sheaf), two runners `sheaf-ci-1` and `sheaf-ci-2`, fork approval set. The script was `/tmp/claude-1000/-home-tiroir-Projects-sheaf/b4a9c79b-20cf-4ed8-8e07-b13889bdaefd/scratchpad/tcompute-group.sh`.
- t-compute part: `/home/tcompute/gh-runner-sheaf/` (Dockerfile on top of `gh-runner:2.338.0`, uid 20301, Firefox and WebKit system libraries; `build-sheaf.sh`, `start-sheaf.sh`, `register-sheaf.sh`, `configure-sheaf.sh`). Containers `gh-runner-sheaf-1` and `-2`: 16 CPUs at cpu-shares 256, 12 GB, shm 2 GB, on `gh-runner-net`, not ephemeral. The image build failed three times with a containerd "lease does not exist" race; `DOCKER_BUILDKIT=0 ./build-sheaf.sh` worked on the fourth. Do not restart or prune the daemon.

## First runs of 545 on the new runners (head ed91c2b0, run 44815284859)

- The 545 rebase is done: head ed91c2b0, pushed; the job landed on `sheaf-ci-1` (runner_name read from the job API).
- Attempt 1 failed at "Install from the lock": `/home/runner/.local` was root-owned in my image, so uv could not write its Python directory. Fixed with `chown -R runner:runner /home/runner` after the install-deps step in the Dockerfile.
- Attempt 2 ran the whole suite with `-n 16`: 10340 passed, 2 failed in 198 s. Both failures had one cause, the image's git 2.43.0 (Ubuntu 24.04): the hub turns its commit look off below git 2.44 (`src/sheafmd/hub/repos.py:216`, "sheaf hub: git below 2.44: commit look off"). The tests are `test_repo_pages.py::test_sheaf_on_a_repo_page_sends_a_report_and_never_its_text` and `test_moved_clone.py::test_moving_back_wakes_the_clone_at_the_next_report_and_it_answers_ok_again`. No test depends on hosted-runner behaviour; the image was behind. Fixed: the Dockerfile adds the git-core PPA and checks for git 2.44 or later; the image has git 2.56.1, containers recreated, both runners online. Attempt 3 (rerun of the failed job) was started under the owner's standing permission for infrastructure failures.
- The slowest 16-worker tests were `test_hub_list` (28 s), `test_service` macOS kickstart (21 s) and `test_ci_scripts` stall-watch (16 s). No timing test failed.

- Attempt 3 (run 44815284859 on sheaf-ci-2, 10340 passed, 2 failed) had two test failures; Kenji said yes to fixing both inside #545 (2026-11-20), with these conditions: no skip below pid 1000; no `--pid=host` on the runner; the leaking test is reported before anything is changed for (b); a fix-diff round is recorded; then "merge #545" when green with a GO.
  - (a) `test_hub_tell.py::test_the_page_never_holds_the_session_id_the_socket_or_the_command[own-pid]`: the worker's pid was 409, and the page holds 409 four times on its own (a status code), with or without a session. Fixed on the branch, committed (not yet pushed): the test compares the count of the pid in the page with the session against the same page without it (`count_number` in `tests/helpers.py`, `holds_number` delegates), and a `409` case guards it on every runner. Verified: the page holds 409 four times before and after attaching; the new assertion passes, the old one fails on 409.
  - (b) `test_hub_upgrade.py::test_a_second_signal_that_interrupts_the_first_inside_the_admit_lock_does_not_hang_the_hub`: `LockOrderViolation` in the thread: the hub of the test has `Checked` locks from `tests/lockorder.py` although test_hub_upgrade is not in `LOCK_ORDER_SUITES` (`tests/conftest.py:124`). `lockorder.install` patches `core.Hub.__init__`, `LiveDocument.__init__` etc. through `monkeypatch`, so something leaves it patched or the patch is applied to another worker's test. Not found yet. Plan: reproduce on t-compute at `-n 4`, then in file order (`-p no:randomly`), then bisect the tests that ran before it on the same worker (gw13 ran 50 test_hub_upgrade tests before it; the earlier tests on that worker are in the run log). Scratch run on t-compute only, `-n 4` at most, scratch dir removed afterwards.

## What is left, in order

1. Read the result of attempt 3 (Monitor, or `gh run view 44815284859`). Check that the Firefox and WebKit page tests started (the page step fails on "page tests were skipped" otherwise), and that the wheel smoke leaves nothing on the runner.
2. Check the jobs really landed on the new runners: `gh api repos/sweatshop-ai/sheaf/actions/runs/<run id>/jobs -q '.jobs[]|"\(.name) \(.runner_name)"'` must show `sheaf-ci-1` or `sheaf-ci-2`.
3. Run the recorded round on the current head (a full round: the base moved).
4. When green with a GO on its current head, tell Kenji "merge #545" (Kenji merges; main is on hold until Oskar's #558 and the v1.3.0 tag) and tell Jonas (cross-track/17) yourself.
5. 545 must never merge before this has run green on the new runners.
