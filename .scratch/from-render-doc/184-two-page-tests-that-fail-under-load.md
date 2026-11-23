# 184: Two page tests fail under load, through races of the tests themselves

**Claimed by:** Nadia

**Status:** in progress

**Priority:** high: each one turns a CI run red on a change that does not touch it.

**Blocked by:** none

**From:** CI, 2026-11-23: the checks of #615 and #617 (run 45151298649), and the nightly run 45141939187

**Where (main 0ba41926):** `tests/page/test_mount_allowlist.py` (`test_control_the_same_corpus_through_innerHTML_does_run_and_does_load`), `tests/page/test_page_writing.py` (`FAIL_TOGETHER`, `test_two_sends_that_fail_at_the_same_instant_on_two_pages_are_both_kept`)

## A. The innerHTML control reads the page while it navigates

### Observed

`test_control_the_same_corpus_through_innerHTML_does_run_and_does_load[chromium]` fails with `Page.evaluate: Execution context was destroyed, most likely because of a navigation` (run 45151298649; #615). Firefox and WebKit pass.

### Cause

The hostile corpus holds `<meta http-equiv=refresh content="0;url=http://evil.test/">`. Through `innerHTML`, Chromium follows it: the route aborts the request and the main frame lands on `chrome-error://chromewebdata/`. A probe of 15 rounds on a loaded runner host saw that landing 30 to 108 ms after the injection, and once 594 ms, against the test's wait of 600 ms. When it lands during the closing `evaluate("window.__pwned || 0")`, that call fails. When it lands before, the error page reads `__pwned` as 0: the control has never shown the "does run" half, only the stranger's address.

Loop: hold the main-frame navigation to the stranger's address until the 600 ms are over, then abort it. The old control fails 10 rounds out of 10 with the CI error.

### Fix

The control counts each `__pwned` the page sets through a Playwright binding (`count_runs_outside_the_page`), so the count is in the test the moment it is set and no read of the page follows the wait. Under the same loop: 10 rounds out of 10 pass, and each round counts 9 runs, where the old control read 0.

## B. The two sends do not race on a loaded machine

### Observed

`test_two_sends_that_fail_at_the_same_instant_on_two_pages_are_both_kept` fails in all three jobs of the nightly run 45141939187 on its guard, not on a lost entry: `rounds [...] did not run the two sends at the same time: the test did not try the race` (16, 17 and 22 idle rounds out of 40, 8 allowed).

### Cause

Each page began to spin with `setTimeout(0)` right after its own send. `keyboard.press` waits until its page has taken the key-up. When page A's spin began before A took the key-up, `a.keyboard.press` returned only once A's spin ended, at the instant, and B's send went out after it: B's spin started 6 to 24 ms after A's ended, so the round did not race. Four copies of the test at once on the runner host gave 1 to 5 such rounds per copy; the nightly's three jobs on one host gave more.

Loop: press with the keys held 30 ms (`press(..., delay=30)`), so the key-up always reaches A after its spin began. The old test: 40 idle rounds out of 40, the CI error.

### Fix

Each page starts to spin at the same fixed time, 300 ms before the instant, whatever the time of its own send; a round now starts 1000 ms ahead of the instant and counts as idle when its setup runs past 500 ms before it. The two failures still come back at the same instant on two renderers, so the test tries the same race. Under the held-key loop: 40 rounds out of 40 race, both spins starting within 1 ms of each other. Four copies of the real test at once: all pass.

## Acceptance

- [ ] Both tests pass in CI on the PR
- [ ] No skip, xfail or retry added; no assertion loosened
