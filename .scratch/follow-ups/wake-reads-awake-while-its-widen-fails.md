# A write whose widen fails leaves a sleeping clone reading awake (Opus recheck, triage line 270)

**What to build:** When `Repos.wake()` cannot bring a sleeping clone's folders back, the clone reads asleep again, without
opening a window in which `sleep_moved()` can mark a clone moved mid-widen.

**Blocked by:** none.

**Status:** open

## The finding

`src/sheafmd/hub/repos.py`, `wake()`: `_use(repo)` clears `sleeping` before `_restore()`. When the widen fails (git
error, no token), the clone reads awake while its folders are still out: `read_only_line` gives the page no "asleep" line,
and the next save fails on the missing file. It heals itself on the next write (`restore` is kept), and no data is lost.

## Why the first fix was dropped (PR 532, review round 3)

PR 532 moved `_use()` after a successful `_restore()`. That opened a race with `sleep_moved()`:

- `sleep_moved()` takes a fast path on `sleeping is True`: it writes `moved` under `_records` only, with no clone lock and
  no shrink, and returns.
- With `_use()` after the widen, a clone being woken still reads `sleeping=True` during the widen. `sleep_moved()` marks
  it moved. Then `wake()`'s `_use()` keeps `moved` but sets `sleeping=False`. The result is a moved clone, awake, with
  its folders checked out in the old tiroir.
- With main's order (`_use()` first), `sleep_moved()` sees `sleeping=False` and goes through the thread path. That path
  runs `_sleep_one` under `holding(dest)`, so it waits for the widen and then shrinks.

`tests/test_clone_sleep.py::test_a_write_widening_a_sleeping_clone_does_not_leave_it_asleep_meanwhile` pins main's order:
the flag reads False during the widen.

## The fix to try

Keep `_use()` before the widen. When the widen does not happen, put `sleeping` back:

```python
self._use(repo)
woken = False
try:
    woken = self._restore(repo, dest, self.provider.token(repo))
finally:
    if not woken:
        self._asleep_again(repo)        # under _records: {**row, "sleeping": True}
return woken
```

The `finally` also covers `provider.token()` raising. A `sleep_moved()` that sees the flag back at True after a failed
widen marks the clone moved on the fast path, which is right: its folders are out.

Before it lands, check:

- [ ] `_use()` also refreshes `last_used` on a failed widen; decide whether a failed widen counts as a use.
- [ ] `sleep_moved()`'s thread path joins for `SLEEP_WAIT` and then reads `moved_to`: with a widen holding the clone lock,
  it can return False to its caller. Confirm the caller asks again.
- [ ] Tests: a widen that fails leaves the clone asleep; a token that cannot be had leaves it asleep (both were written on
  the PR 532 branch at 116c925d and dropped with the change).
