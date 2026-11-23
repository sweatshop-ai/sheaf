# 184: Two page tests fail under load, through races of the tests themselves

**Claimed by:** Nadia

**Status:** A and B done in #620 (merge 4d34e1ad, head 9f21f8df), CI green (run 45178873288), review GO (round 1, provisional: Opus fallback, Codex at its usage limit). C and D open.

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

The test gives each page only the key-downs of Control+Enter before the instant (the send is on keydown, `page.js`) and both key-ups after it. A key-down is taken while its event is handled, before the spin's timer fires, so page B's send no longer waits for page A. Each page still spins from its own send on, so neither hears the other's send-time write before its own send fails: the variant the test's comment names (the store seen without the other's entry) is still the one tried.

A first fix started both spins at a fixed time 300 ms before the instant. It raced, but the review of the PR saw that it gave each page some 200 ms to hear the other's write first, so it tried a narrower race; it was replaced before merge.

Four copies of the test at once on the runner host: 160 rounds out of 160 race, B's spin starting at most 18 ms after A's (the same load gave 13 idle rounds before). The keys are now held through the instant in every round, the condition that made 40 rounds out of 40 idle with `press`.

## Acceptance

- [x] Both tests pass in CI on the PR (run 45178873288: the control in chromium, firefox and webkit, and the two sends)
- [x] No skip, xfail or retry added; no assertion loosened

## Open: other page tests seen red in the same runs (not looked into)

- [ ] **C.** `tests/page/test_page_move_box.py`: `test_a_box_moved_to_the_lower_right_is_inside_the_window_after_it_shrinks` ("timed out waiting for the moved box back inside the smaller window") and `test_a_box_moved_to_the_foot_that_grows_with_a_reply_keeps_its_controls_in_view` ("timed out waiting for the grown box inside the window"), both at `tests/page/pagehelp.py:195`, in run 45151298649 (job py3.13, the checks of #617).
- [ ] **D.** `tests/page/test_sheaf_buttons.py::test_the_view_switch_shows_pages_archived_and_trash_each_with_its_own_list` ("timed out waiting for Archived: alpha only"), in the nightly run 45141939187, job py3.11 only (py3.13 and py3.14 passed it).
