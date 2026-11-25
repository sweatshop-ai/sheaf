# 192: Codex NO-GO findings on merged PRs #590 and #592 (pin age in a root, SIGTERM in a route callback)

**Claimed by:** Wilma

**Status:** open (number claimed; fixing on `wilma/192-pin-age-and-route-greenlet`)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone (#590 round06, #592 round05). Each finding was checked
against `origin/main` at 61783779.

## #590: pin age

- [ ] A [SERIOUS] `VersionStore.get` judges a pin's age by the file's mtime. A root's own versions store goes to git
  (8.11), and a clone or checkout writes every pin file with the time of the checkout, so a pin last pinned weeks before is
  believed again for 7 days, and a save, reply or Tell is accepted against a version no page holds any more. Holds on main
  (`src/sheafmd/hub/state.py` `get`, `stat().st_mtime`). Fix test-first: the age of a pin in a root's store comes from
  something git carries, not from the file's mtime.

## #592: SIGTERM during a test

- [ ] B [SERIOUS] `tests/leakguard.py` `_terminated` throws the interrupt into the thread's first greenlet whenever the signal
  lands elsewhere. Playwright runs a synchronous route callback in a `RouteGreenlet` whose parent is the dispatcher: thrown
  past it, the callback stays suspended, its future never resolves and `Page._on_route` stays pending (or an unroute waits
  for ever), the teardown failure #592 meant to end. Holds on main. Fix test-first.
