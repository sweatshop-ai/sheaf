# 101: macOS: a run on main on every Python, and the readings only a real Mac can check

**Status:** open

**From:** render-doc ticket 101 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `.github/workflows/ci.yml:15-16`, `:67-69`, `tests/test_hub_upgrade.py:130`

**Size:** one CI run, one comment edit, one by-hand session on a Mac

- [ ] **macOS has run on one Python only, once, on a branch.** Run 41025108862 (a branch, head `9324e44`, 2026-10-30) has `macos-26 py3.13: success` with every step green, including the page tests, the wheel smoke and the launchd user service. Of the 39 manual runs of `ci.yml`, the macOS jobs ran only on py3.13; py3.11 and py3.14 never ran on macOS, and no macOS job has run on main since PR #98 (the stop-race fix in the client). Run `gh workflow run ci.yml --ref main -f python=all -f macos=true`. That settles the py3.11 case of `tests/test_hub_upgrade.py:130` (an upgrade stop under the service exits 75), which failed on macOS py3.11 before the fix, and shows whether main still passes on macOS.

- [ ] **The workflow comments say macOS has never been green.** `.github/workflows/ci.yml:15-16` and `:67-69` ("no macOS run has been green yet"). Run 41025108862 was green. Reword them after the main run above.

- [ ] **Readings of real-world data not verified on a real Mac.** The `procStart` format a coding agent's session record carries on macOS (read by `proc_start` through `ps -o lstart=`); `ps` output for a zombie; BSD `wc` padding; `launchctl bootout`/`bootstrap` timing with no GUI session. The CI run covers the tests, not these.
