# test_page_dictation's recording-dropped test is flaky

**What to build:** `tests/page/test_page_dictation.py::test_a_recording_is_dropped_when_the_service_is_lost_during_it` failed once, in the Chromium page-test fixture (`tests/page/conftest.py`, the `tab` fixture), at `p.wait_for_function("window.__mic.stops === 1")` (line 219, straight after `p.clock.run_for(15000)`). Error: `playwright._impl._errors.Error: Page.wait_for_function: EvalError: Evaluating a string as JavaScript violates the following Content Security Policy directive because 'unsafe-eval' is not an allowed source of script: script-src 'nonce-...'`, followed in the warnings summary by `RuntimeError: no running event loop` (from Playwright's `Page._on_route`, a teardown warning, not the failure itself). Seen on main 4ed14342 (docs-only #358), run 43656456618, job 132635928007 (`ubuntu-24.04 py3.13 slice 1/3`, Page tests). The same test passed on fa3cd7e1, and the re-run of the failed job passed. The cause is not found: the same test's earlier string wait (`window.__mic.made.length === 1 ...`, line 215) evaluated fine in the same run. Make the waits not evaluate a string under the page's CSP: pass a function (`p.wait_for_function("() => window.__mic.stops === 1")`) or poll from Python (`until(lambda: p.evaluate(...) == 1)` from `tests/page/pagehelp.py`, which `test_page_writing.py` uses), in this test and the other string waits in `test_page_dictation.py`.

(Written by Bodil at Tarek's request, 2026-11-15.)

**Blocked by:** None.

**Status:** done

- [x] The waits of this test no longer pass a string to `wait_for_function`
- [x] The test no longer fails when the runner is slow (run it 20 times on t-compute under load)

  Evidence 2026-11-20: already on main in b184c39f (function predicates; tests/test_page_predicates.py guards it); both tests run 20 times in a row on t-compute at origin/main 3f5271bd (load 64-83 on 32 cores): 20 of 20 runs passed (3 tests each, the writing one in two parametrized cases), none failed.

  Evidence 2026-11-20: already on main in b184c39f (no string `wait_for_function` is left under tests/); the whole of test_page_dictation.py run 30 times (10 parallel loops sharing 4 cores on t-compute, main e5f10c6f): 30 of 30 passed, 0 failed.
