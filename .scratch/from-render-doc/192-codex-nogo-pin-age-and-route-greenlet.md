# 192: Codex NO-GO findings on merged PRs #590 and #592 (pin age in a root, SIGTERM in a route callback)

**Claimed by:** Wilma

**Status:** done (#659, merged as c0c9dca0)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone (#590 round06, #592 round05). Each finding was checked
against `origin/main` at 61783779.

## #590: pin age

- [x] A [SERIOUS] `VersionStore.get` judges a pin's age by the file's mtime. A root's own versions store goes to git
  (8.11), and a clone or checkout writes every pin file with the time of the checkout, so a pin last pinned weeks before is
  believed again for 7 days, and a save, reply or Tell is accepted against a version no page holds any more. Holds on main
  (`src/sheafmd/hub/state.py` `get`, `stat().st_mtime`). Fix test-first: the age of a pin in a root's store comes from
  something git carries, not from the file's mtime.

## #592: SIGTERM during a test

- [x] B [SERIOUS] `tests/leakguard.py` `_terminated` throws the interrupt into the thread's first greenlet whenever the signal
  lands elsewhere. Playwright runs a synchronous route callback in a `RouteGreenlet` whose parent is the dispatcher: thrown
  past it, the callback stays suspended, its future never resolves and `Page._on_route` stays pending (or an unroute waits
  for ever), the teardown failure #592 meant to end. Holds on main. Fix test-first.

## Evidence

- **A, fixed in #659.** In a root's own store a pin's time is in `<hash>.at` beside it (ns since the epoch), written before
  the pin; `get` and the 16-per-member order read it, the state folder keeps mtime. Not "something git carries", as the box
  asked: the first review round of #659 showed that a time in git differs between two clones pinning one version and
  makes their sync conflict, which stops every later push. So `.sheaf/versions/.gitignore` (`*.at`, itself) keeps each
  hub's times local: a fresh clone or checkout has none and believes no old pin, which is the defect. Also not believed:
  a time file that is a link or a FIFO (`read_small`), holds no number, or lies more than a minute ahead. SPEC 7.4, the
  files table and CHANGELOG say so. Tests, red before: `tests/test_hub_state.py`
  `test_a_pin_of_a_roots_own_store_keeps_its_age_through_a_clone_or_checkout`,
  `test_a_pin_of_a_roots_own_store_with_no_time_beside_it_is_not_believed`,
  `test_a_pins_time_stays_out_of_git_so_two_clones_pinning_one_version_never_conflict`.
- **B, fixed in #659.** `_terminated` raises the signal again at the first switch away from a greenlet whose parent is not
  the first one (a route callback's), so it lands in the dispatcher and goes on as before; a second SIGTERM while one
  waits is raised where the test stands at once, so a callback that never switches away cannot swallow it. Tests, red
  before: `tests/test_leakguard.py`
  `test_a_sigterm_in_a_route_callback_lets_the_callback_finish_before_it_is_raised_where_the_test_stands`,
  `test_a_second_sigterm_in_a_route_callback_that_never_switches_away_reaches_the_test_at_once`.
- **Review.** Standards and spec review (fixes in the same push); Opus fallback round01 NO-GO (the git conflict above),
  round02 on the fix GO. CI green on b87746d9.

## Left open

- [MINOR] A pin another clone made has no time on this clone, so it sorts oldest among the 16 of one member and is
  dropped first; the drop is committed and pulled, and a page on the other clone that still holds it gets the 409. Needs
  more than 16 pins by one member on one document across two clones.
- [MINOR] Pins written before #659 have no time file: after the upgrade a page holding its reload across the restart can
  get the 409 until its next daily pin (CHANGELOG says so).
