# Handoff: ticket 173 Q and O, for the next macOS batch run

**From:** Milos, 2026-11-23. **Boss:** Kaveh, track sheaf-backlog.
**State:** nothing open in git. PR 614 (173 Q) is merged as `fc2e3644`. No worktree or branch is left. No macOS run has been dispatched since 45133232164.

The next batch is one run on main, dispatched by the boss: `gh workflow run ci.yml --ref main -f python=all -f macos=true`. Fetch a log with `gh api repos/sweatshop-ai/sheaf/actions/jobs/<job>/logs > <job>.log`.

## Ticket 96 box 2: done

The launchd exit-75 check (PR 613, `tools/ci/service_macos.py`) printed ok on macOS py3.11, 3.13 and 3.14 in run 45133232164 (jobs 137553339795, 137553339977, 137553340151). The check now fails CI on a wrong code. Nothing to do in the batch except to note it if it goes red.

## 173 Q: the cancel test's stop message (open until the batch)

**Test:** `tests/test_hub_tell.py::test_cancelling_a_delivery_still_running_kills_it_and_sends_the_stop_message`. It was red on macOS py3.11 slice 5 in job 137553339954.

**Fix in PR 614 (tests only):**
- The wait for the stop message is now the term grace plus 5 s.
- When the stop takes more than 1 s, the test reads the cancelled delivery's process group 1 s or more after the cancel and puts it in a `UserWarning` (or in the failure, if the stop never comes), with the jobs and the hub's diagnostics.

**What to read in the batch, on every macOS Python, slice 5:**
- Did the test pass? Tick Q only if it passed on all three Pythons.
- Look for the warning `the stop message came … s after the cancel; the delivery's group [...]` in the warnings summary. If it is there, the group list names the process that held the stop up on macOS. That is the evidence the box lacks: write it into Q.
- No warning and green: the stop came within 1 s, so this run does not explain the earlier red. Say so in Q.

**Not established:** which process held the stop up on the Mac. The fake (`/bin/sh` with `cat`, `mv` and `sleep`) traps nothing. A child outliving SIGTERM is the hypothesis that fits and was reproduced on Linux by injection. It is not a finding.

## 173 O: the reload stall (open)

**Test:** `tests/page/test_page_actions.py::test_a_box_typed_in_a_block_whose_save_is_merged_is_not_ticked_before_the_reload`, slice 6.

**Record:** green on all three Pythons in runs 45120326342 and 45133232164. The cause of the earlier stall (`PageStalled`, then the Playwright driver stopped answering) is not established.

**What to read in the batch:**
- On a `PageStalled` or a pytest-timeout, CI uploads the `stall-evidence-…` artifact (PR 609). Read the page journals, the hub log and the stacks in it before anything else.
- Green again: add the run to O. One more green does not close O, because its cause is still unknown.

## Side fix in the same PR

`tests/test_helpers_exec.py:61` runs `true` from PATH, because the macOS image has no `/bin/true`. In the batch, the `FileNotFoundError` thread warnings should be gone from every macOS log. If they are not, note it in 173.
