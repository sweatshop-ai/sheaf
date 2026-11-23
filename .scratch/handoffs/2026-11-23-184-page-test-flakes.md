# Handoff: ticket 184 A and B, two page tests that failed under load

**State:** A and B done, merged in #620 (4d34e1ad). C and D open in the ticket, not looked into.

## Done
- **184 A**, `test_control_the_same_corpus_through_innerHTML_does_run_and_does_load[chromium]`: the corpus's meta refresh takes Chromium's main frame to its error page up to about 600 ms after the injection, and the closing read of `__pwned` hit that navigation. The control now counts runs through a Playwright binding (`count_runs_outside_the_page`). Red loop (the navigation held to the end of the wait): 10/10 red before, 10/10 green after.
- **184 B**, `test_two_sends_that_fail_at_the_same_instant_on_two_pages_are_both_kept`: `keyboard.press` waits for its page's key-up, so a page already spinning held the other page's send past the instant. The test now gives key-downs before the instant and key-ups after it; each page still spins from its own send. Red loop (key held 30 ms): 40/40 idle rounds before; after, 160/160 rounds raced with four copies at once on the runner host.
- The first fix for B (both spins at a fixed time) narrowed the race: the spec review caught it, and it was replaced before merge.
- CI run 45178873288 green on head 9f21f8df. Review round 1: Matt's code-review, then `boss_review` provisional GO (Opus fallback, Codex at its usage limit until 2026-11-24 12:39 UTC).
- Branch `nadia/184-page-test-flakes` and worktree `sheaf-wt-nadia-184` removed, local and remote.

## Next
1. **184 C**: the two `test_page_move_box` time-outs of run 45151298649.
2. **184 D**: the `test_sheaf_buttons` view-switch time-out, nightly 45141939187, py3.11 only.
3. A Codex recheck of #620's provisional round, if the track asks for one.
