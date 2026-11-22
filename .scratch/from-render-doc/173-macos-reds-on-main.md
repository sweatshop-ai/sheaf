# 173: macOS is red on main: xdist workers die and the run ends early

**Claimed by:** Wanda 2026-11-20

**Status:** open

**Blocked by:** none

**From:** ticket 101 (run 44776626154)

**Where (main 438fb0e9):** `.github/workflows/ci.yml:105` (`pytest -v -n 4 ... -m "not page"`), `tests/conftest.py`, the tests listed below

**Size:** unknown until the failure list is clean; one cause per PR

Run 44776626154 (manual, `python=all macos=true`, main 438fb0e9, 2026-11-20): all 18 macOS slices (`macos-26`, py3.11, py3.13, py3.14, slices 1 to 6) failed, every one of them at the Tests step with exit code 3. Ubuntu is not part of this ticket (that run had two ubuntu failures of its own: py3.14 slice 2/6 and py3.11 slice 5/6; not read).

- [ ] **A slice ends in an xdist crash after 3 to 7 percent of its tests.** Every macOS slice logs `[gwN] node down: Not properly terminated`, then `replacing crashed worker gwN` (2 to 6 times per slice), then `INTERNALERROR> KeyError: <WorkerController gwN>` from `xdist/scheduler/loadscope.py:275` (`_assign_work_unit`, reached through `worker_collectionfinish`), and the run stops (`1 failed, 72 passed in 47.74s` for py3.13 slice 1/6). So the real failure list is unknown: most of each slice never ran. Two causes to separate: what kills a worker, and the scheduler losing track of the replacement.

- [ ] **The tests whose worker died.** Each of these is reported FAILED in the slice named; the same test fails on every Python, so this is not a version matter.

| Test file::test | py3.11 | py3.13 | py3.14 |
|---|---|---|---|
| test_agent_tokens.py::test_an_agent_no_member_names_signs_with_the_hubs_person | s1 | s1 | s1 |
| test_agent_tokens.py::test_a_token_made_before_agents_signs_as_it_always_did_and_is_no_agent | s2 | s2 | s2 |
| test_agent_tokens.py::test_a_reply_by_an_agent_of_a_member_is_signed_client_and_member | s4 | s4 | s4 |
| test_agent_tokens.py::test_a_running_hub_keeps_the_binding_it_started_with_while_the_table_is_broken_on_disk | s4 | s4 | s4 |
| test_agent_tokens.py::test_renaming_the_member_changes_the_signature_after_a_restart | s5 | s5 | s5 |
| test_agent_tokens.py::test_in_loopback_mode_an_agent_signs_with_the_hubs_person_and_never_as_the_bare_person | s6 | s6 | s6 |
| test_acting_races_move.py::test_a_move_between_the_read_of_the_path_and_the_write_of_the_mark_leaves_no_mark_at_the_old_path (keep-keep.json-body0) | s4 | s4 | s4 |
| same test (restore-seen.json-body2) | s6 | s6 | s6 |
| test_isolation.py::test_a_command_that_starts_a_hub_starts_it_on_that_port | s3 | s3 | s3 |
| test_isolation.py::test_the_hub_that_test_started_was_stopped_when_it_ended | s3 | s3 | s3 |
| test_hub_pusher_settles.py::test_a_test_that_ends_with_a_push_due_leaves_it_to_its_own_teardown | s5 | s5 | s5 |
| test_hub_built_outside_the_fixture_settles.py::test_a_hub_built_outside_the_fixture_ends_with_a_push_due | s2 | s2 | s2 |
| test_answer_replies_survive.py (several parametrised cases: the sibling-comment rewrite, the thread rewrite, "reads as an answer before the hub touches the file") | s2, s3, s5, s6 | s2, s3, s5 | s2, s3, s5 |

Which parametrised cases fail differs from run to run of the slice, as expected when a worker dies mid-test. All of these start a hub (a subprocess); no test outside that group was reported failed.

**Finding (2026-11-20).** Run 44788583073 (branch run, macos-26 py3.13, `-p no:xdist`, the six files above): pytest itself died on its first test, `test_agent_tokens.py::test_a_reply_by_an_agent_of_a_member_is_signed_client_and_member`, with exit code 140 (128 + 12, SIGSYS). Under xdist the same death kills a worker, and xdist's `loadscope` scheduler then raises `KeyError: <WorkerController gwN>` on the replacement worker. Cause: `src/sheafmd/beneath.py` `_openat2` calls `libc.syscall(437, ...)`, Linux's `openat2`; only the check `hasattr(_LIBC, "syscall")` guarded it, and macOS has `syscall`. Fix: PR 514 (`openat2` only where `sys.platform` starts with `linux`; `tests/test_beneath_platform.py` red before, green after). Proof on a macOS runner: run 44789641813 (fix applied, same six files, no xdist): 106 passed in 91.7 s, then the job was cancelled by the 40 minute cap of the diagnosis branch while in the page tests (that cap is not in main).

**The list with the crash gone (run 44797348240: main plus PR 514, macos-26 py3.13, all six slices, xdist on).** Each slice now runs to its end (about 1,700 tests, 8 to 10 minutes) and 1 to 4 tests fail per slice, 16 in all. By cause:

| Cause | Tests | Evidence |
|---|---|---|
| A. A test reads `/proc`, which macOS has not | `test_send.py::test_a_tiroir_that_hangs_or_fails_leaves_the_page_on_the_laptop_hub_with_the_loud_line` ([500], [503], [hang]); `test_hub_transcribe.py::test_a_failure_inside_fdopen_neither_leaks_nor_double_closes_a_descriptor` | `FileNotFoundError: '/proc'`, `'/proc/self/fd'` |
| B. Counts of path resolutions and `lstat` calls differ, under `/private/var/folders` (a symlinked temp dir) | `test_listing_realpath_calls.py` (two tests), `test_listing_resolves_once.py::test_the_sheaf_listing_resolves_folders_once_per_listing_not_per_page` | `153 resolutions of 55 paths`; `494 folder lstat calls for 10 pages` |
| C. The "file cannot be read" message differs from the expected one | `test_hub_visibility.py::test_a_token_that_saw_a_sheaf_is_told_when_its_file_cannot_be_read` ([read-args0], [threads-args1], [reply-args2] with `unreadable`) | the answer ends in "`sheaf diag`." where the test expects "... not be read." |
| D. A test hub is not stopped, or not started on its port | `test_isolation.py` (two tests) | `assert ([])` |
| E. The guard that finds a signalled foreign pid fires | `test_real_hub_untouched.py` (two tests), `test_hub_commits.py::test_a_git_that_failed_before_the_stop_signalled_it_is_a_failure_...` | `a test signalled pid 3791 (15), a process it did not start` |
| F. A message differs | `test_repo_pages.py::test_a_page_of_a_repo_that_is_anothers_private_root_renders_on_the_laptop_with_one_line_naming_no_one` | `'not cloned'` expected in the output |

Causes are read from the assertion text only: none of A to F is diagnosed yet. One PR per cause.

**Progress (2026-11-20).**
- **A: done, PR 547 (merged 636dd296).** `children()` in `test_send.py` asks `ps` where there is no `/proc` (and leaves out its own `ps`); `test_hub_transcribe.py` lists `/dev/fd` where there is no `/proc/self/fd`. Tests only. macOS py3.13, the four tests, no xdist: red run 44805030223 (4 of 4 `FileNotFoundError: '/proc'`), green run 44811109769 (`4 passed in 38.72s`).
- **B: done, PR 562 (merged 14a2fcc3).** Cause read from the stacks of run 44813927978: `beneath._walk` resolves its root with `os.path.realpath(top)` for every file it opens (`src/sheafmd/beneath.py:222`), because macOS has no `openat2` and always takes that walk; the two listing tests counted those calls. It is the containment guard re-resolving its root on purpose, so the source is unchanged: `helpers.in_beneath_walk()` leaves those calls out of both counts where `openat2` is not in use. macOS py3.13, the two files, no xdist: red 44813927978, green run 44818580480 (`3 passed in 5.35s`).
- **C to F: diagnosed, one PR each (2026-11-22).** All four rebased on main 6151327f; each commit identical to the one macOS ran (range-diff); then main merged in (no rebase), the diff each adds to main patch-id equal to the reviewed one.
  - **D merged** (PR 567, merge 5656259f, head b9bdc70f). **E merged** (PR 564, merge c1c198a7, head e5942ea0). **F merged** (PR 565, merge e6fa3109, head fcb0ba7d, full round 2 GO after main changed `tests/test_repo_pages.py`).
  - **C, PR 563: waiting for merge** (merge head a2f0f62b, full round 5 GO; one ubuntu slice failed on `test_hub_upgrade.py::test_a_second_signal_that_interrupts_the_first_inside_the_admit_lock_does_not_hang_the_hub`, a flaky test seen on main and seven other branches, see `.scratch/follow-ups/own-patches-restores-over-a-mid-test-undo.md`; job rerun). Before: head 3c1689ac, Codex round 2 GO. macOS has no `os.O_PATH`, so a mode 000 file opened with `meta` raised AttributeError, which the hub answered as its own failure ("... `sheaf diag`."). `beneath._walk` now takes the identity and status of such a file from its folder, no descriptor; `Opened.stat()` returns that status (never asked of the name again: round 1 NO-GO, a file put in its place could be described instead; test added); two callers in `hub/core.py`. macOS py3.13: red 44828043440 / 44829164316 (`O_EVTONLY` refused too), green 44829666695 (`181 passed`).
  - **D, PR 567** (head 568fd747, Opus GO). The hub-start test in `test_isolation.py` waited 3 s for a reply on a loaded runner under xdist; it sets `client.TIMEOUT` to 30 s. Red 44830319803 / 44831400077, green 44832094797 (`106 passed`).
  - **E, PR 564** (head 0899767e, Opus GO). `leakguard.carries_this_run` asks `ps -E` where there is no `/proc`; the guard's own signal 0 probes are no longer counted by `Log.sent()`. Red 44826956852, green 44828043440. Two minor findings left for later, tests only: on macOS the guard's own `ps` goes through the tracked Popen, so its pid joins `spawned.pids`; a missing or failing `ps` surfaces as an error from inside `os.kill`, not a clean refusal.
  - **F, PR 565** (head 5a4470e8, Opus GO). macOS temp dirs sit under `/private/var/folders`, so the "private" word check in `test_repo_pages.py` matched the page path; it now ignores the path. Red 44826956852, green 44828043440.
  - Diagnosis branches deleted (their fixes are in the PRs above; the rest was CI edits for diagnosis).
  - After the four merge: one `ci.yml` run on main with `python=all macos=true`, then the boxes above.

- [x] **Get a clean failure list.** Start a manual run on a branch for one Python (py3.13) with xdist off (`-p no:xdist`) or at `-n 2`, on the failing slices only, and read the first real traceback of each test. Cost: macOS minutes count ten times, so one Python, only the slices above.

- [ ] **Group the failures by cause, fix only what a macOS runner proves.** One cause per PR. Cause of the worker deaths: not yet read.

Not covered here, kept in ticket 101: the readings only a real Mac can check.
