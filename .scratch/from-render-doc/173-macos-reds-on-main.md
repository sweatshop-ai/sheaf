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

- [ ] **Get a clean failure list.** Start a manual run on a branch for one Python (py3.13) with xdist off (`-p no:xdist`) or at `-n 2`, on the failing slices only, and read the first real traceback of each test. Cost: macOS minutes count ten times, so one Python, only the slices above.

- [ ] **Group the failures by cause, fix only what a macOS runner proves.** One cause per PR. Cause of the worker deaths: not yet read.

Not covered here, kept in ticket 101: the readings only a real Mac can check.
