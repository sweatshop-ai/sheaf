# 96: Packaging follow-ups: macOS CI green, launchd on a real Mac, Windows on a real Windows

**Status:** open

**From:** render-doc ticket 96 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `.github/workflows/ci.yml:67-70`, `tools/ci/service_macos.py:93-97`, `SPEC.md:1636`, `SPEC.md:1772`, `README.md:80`, `src/sheafmd/cli.py:1161-1175`, `tests/test_windows_gate.py`, `SPEC.md:1026`, `:1071`, `:1229`

**Size:** five items; the macOS ones overlap ticket 101

- [ ] **macOS CI has never been green on main.** `.github/workflows/ci.yml:67-70` runs `macos-26` only on a manual dispatch; the run recorded there (run 40980723217, 2026-10-30) was red on sheaf's side (`test_hub_recover` and others). SPEC.md:1772 says the same. Get one green manual macOS run (see ticket 101 for the one green branch run and the command).

- [ ] **The launchd exit-75 check is only a notice.** Once a macOS runner has printed `launchctl print` and its format is known, make the "last exit code = 75" check in `tools/ci/service_macos.py:93-97` a failure instead of a `_ci.notice`, so an upgrade stop that does not exit 75 on launchd fails CI.

- [ ] **A launchd service has never run on a real Mac.** Install, upgrade stop, uninstall, by hand. SPEC.md:1636 says sheaf has not been run on a Mac.

- [ ] **Native Windows is only tested with a faked platform.** The gate (`cli.windows_stops`, `src/sheafmd/cli.py:1161-1175`) is tested in `tests/test_windows_gate.py` with the platform faked; SPEC.md:1636 and README.md:80 say it was never run on a real Windows. Run `uv tool install sheafmd`, `sheaf version`, `sheaf FILE --share` and `sheaf comments FILE` on a real Windows (a hosted `windows-latest` runner is free on a public repo) and check the other commands stop with the WSL2 sentence.

- [ ] **SPEC examples carry a real first name and a personal host name.** `SPEC.md:1026` (the `shared:` example), `SPEC.md:1071` (the `host:`/`member:` example) and `SPEC.md:1229` (the "seen by ... in trial 2" note). Replace with neutral example names. The wider sweep of the tree is ticket 155.
