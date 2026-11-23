# 101: macOS: a run on main on every Python, and the readings only a real Mac can check

**Claimed by:** Wanda 2026-11-20 17:44

**Status:** done (box 3, the Mac-only readings, stays unticked: each reading needs a real Mac, reason per item)

**Blocked by:** none

**From:** render-doc ticket 101 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `.github/workflows/ci.yml:15-16`, `:67-69`, `tests/test_hub_upgrade.py:130`

**Size:** one CI run, one comment edit, one by-hand session on a Mac

- [x] **macOS has run on one Python only, once, on a branch.** Run 41025108862 (a branch, head `9324e44`, 2026-10-30) has `macos-26 py3.13: success` with every step green, including the page tests, the wheel smoke and the launchd user service. Of the 39 manual runs of `ci.yml`, the macOS jobs ran only on py3.13; py3.11 and py3.14 never ran on macOS, and no macOS job has run on main since PR #98 (the stop-race fix in the client). Run `gh workflow run ci.yml --ref main -f python=all -f macos=true`. That settles the py3.11 case of `tests/test_hub_upgrade.py:130` (an upgrade stop under the service exits 75), which failed on macOS py3.11 before the fix, and shows whether main still passes on macOS.

  **Result (2026-11-20, run 44776626154 on main 438fb0e9, `python=all macos=true`):** all 18 macOS slices (py3.11, py3.13, py3.14, slices 1 to 6) failed at the Tests step: xdist workers die (`node down: Not properly terminated`) and the run ends in `INTERNALERROR> KeyError: <WorkerController gwN>` after 3 to 7 percent of the tests. The failing tests, per Python and slice, are in ticket 173. The py3.11 case of `tests/test_hub_upgrade.py:130` is NOT settled: no macOS slice got far enough to run it. The wheel smoke and the launchd service steps did not run (the job stops at Tests). This box stays open until ticket 173 gives a macOS run that reaches the end.

  **Result (2026-11-23, run 45103186031 on main bdd1d9ef, `python=all macos=true`):** every macOS job ran to its end. 16 of 18 green; 2 red, both py3.14 (slice 3: ticket 173 P; slice 6: ticket 173 O, the driver stopped answering). py3.11 and py3.13 green on all six slices. Ubuntu 18 of 18 green. This box stays open until a run is green on all three Pythons.

  **Result (2026-11-23, run 45120326342 on main ec8d1707, `python=all macos=true`): closed.** All 36 jobs green: macOS 18 of 18 (py3.11, py3.13, py3.14, slices 1 to 6) and Ubuntu 18 of 18. On every macOS job the Tests, Page tests and Wheel smoke steps passed; `User service, launchd` passed on slice 1 of each Python (jobs 137512372974, 137512373174, 137512373189). The py3.11 case of `tests/test_hub_upgrade.py:130` (`test_an_upgrade_stop_under_the_service_exits_75_and_the_supervisor_starts_the_new_code`) passed on macOS py3.11 slice 3 (job 137512373055), and on py3.13 and py3.14 slice 3. The ticket 173 O stall did not recur in this run, but its cause is not established (ticket 173).

- [x] **The workflow comments say macOS has never been green.** `.github/workflows/ci.yml:15-16` and `:67-69` ("no macOS run has been green yet"). Run 41025108862 was green. Reword them after the main run above. Done: PR 499, merged as 71261793; `.github/workflows/ci.yml` on main now says "green once on a branch (41025108862), red on main (44776626154)" in both places.

- [ ] **Readings of real-world data not verified on a real Mac.** Stays open; each reading, and why a CI run cannot settle it:
  - The `procStart` format a coding agent's session record carries on macOS, read by `proc_start` through `ps -o lstart=`: CI has no coding agent session, so only a Mac with a live agent shows the real string.
  - `ps` output for a zombie (state letter and the `lstart` of a defunct process): a CI test can make a zombie but the reading in question is what a real session leaves behind; check on a Mac.
  - BSD `wc` padding (`wc -l` pads with spaces on macOS): CI runs it but only on the strings the tests feed; check the call sites that parse a count from real output.
  - `launchctl bootout`/`bootstrap` timing with no GUI session: the runner has a GUI session, a headless login does not; only a Mac logged in over ssh with no console user shows the timing.
