# 96: Packaging follow-ups: macOS CI green, launchd on a real Mac, Windows on a real Windows

**Status:** open (box 2 needs a fix; boxes 3 and 4 need a real Mac and a real Windows)

**Blocked by:** none (173 blocked box 1, now ticked)

**From:** render-doc ticket 96 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `.github/workflows/ci.yml:67-70`, `tools/ci/service_macos.py:93-97`, `SPEC.md:1636`, `SPEC.md:1772`, `README.md:80`, `src/sheafmd/cli.py:1161-1175`, `tests/test_windows_gate.py`, `SPEC.md:1026`, `:1071`, `:1229`

**Size:** five items; the macOS ones overlap ticket 101

- [x] **macOS CI has never been green on main.** `.github/workflows/ci.yml:67-70` runs `macos-26` only on a manual dispatch; the run recorded there (run 40980723217, 2026-10-30) was red on sheaf's side (`test_hub_recover` and others). SPEC.md:1772 says the same. Get one green manual macOS run (see ticket 101 for the one green branch run and the command).
  **Done (2026-11-23):** run 45120326342 on main ec8d1707 (`python=all macos=true`, 2026-11-23) is green on all 36 jobs, macOS 18 of 18 on py3.11, 3.13 and 3.14 (ticket 101, box 1).

- [ ] **The launchd exit-75 check is only a notice.** Once a macOS runner has printed `launchctl print` and its format is known, make the "last exit code = 75" check in `tools/ci/service_macos.py:93-97` a failure instead of a `_ci.notice`, so an upgrade stop that does not exit 75 on launchd fails CI.
  **Open, the format is now known (2026-11-23).** In run 45120326342 on main ec8d1707 (`python=all macos=true`, 2026-11-23) slice 1 of each Python (jobs 137512372974, 137512373174, 137512373189) logs `launchctl print says last exit code = 75:: exit 75 is shown by the hub-exit row only`: launchd did record 75, but `launchd_job()` reads it with `last exit code = (\S+)` (`tools/ci/service_macos.py:38`), which takes `75:` with its colon, so `last == "75"` is false and the notice fires on a correct exit. Next: read the number only (`(-?\d+)`), then turn the notice into a failure; a macOS runner must show the new check green before this box is ticked.

- [ ] **A launchd service has never run on a real Mac.** Install, upgrade stop, uninstall, by hand. SPEC.md:1636 says sheaf has not been run on a Mac.
  **Open, Mac-only:** the CI runner runs install, kill -9, upgrade stop and uninstall under launchd (green in 45120326342), but in its own GUI session on a fresh image; a by-hand install on a real Mac, with a login and an upgrade from an installed release, is not shown by any run.

- [ ] **Native Windows is only tested with a faked platform.** The gate (`cli.windows_stops`, `src/sheafmd/cli.py:1161-1175`) is tested in `tests/test_windows_gate.py` with the platform faked; SPEC.md:1636 and README.md:80 say it was never run on a real Windows. Run `uv tool install sheafmd`, `sheaf version`, `sheaf FILE --share` and `sheaf comments FILE` on a real Windows (a hosted `windows-latest` runner is free on a public repo) and check the other commands stop with the WSL2 sentence.
  **Open, Windows-only:** no run on Windows exists, hosted or real; the gate is only tested with the platform faked.

- [x] **SPEC examples carry a real first name and a personal host name.** `SPEC.md:1026` (the `shared:` example), `SPEC.md:1071` (the `host:`/`member:` example) and `SPEC.md:1229` (the "seen by ... in trial 2" note). Replace with neutral example names. The wider sweep of the tree is ticket 155.
  - Cleaned by 6580535f (2026-11-16, "Use generic names in the spec, glossary and notes"), on main: the three examples now read `alice`, `agency-tiroir`/`alice-laptop` and a neutral trial note (`SPEC.md:1099`, `:1151-1152`, `:1317` on main d497aacc+). `git grep -i -w` of the owner's and team's first names over `SPEC.md` on origin/main: 0.
