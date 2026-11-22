# `own_patches` restores what it captured, also after a test's `monkeypatch.undo()`

**What to build:** A mid-test `monkeypatch.undo()` must never leave a patch behind in the process.

**Blocked by:** None.

**Status:** open

## Problem

`own_patches` (tests/conftest.py) is a `MonkeyPatch` of its own, undone after the test's `monkeypatch`, so that a test's `monkeypatch.undo()` does not lift the autouse patches (the home, the state folders). It restores the value it read when it patched. When another fixture patched the same attribute before it through the shared `monkeypatch`, that value is the other fixture's patch, and a mid-test `monkeypatch.undo()` has already put the real one back. At the end `own_patches` writes the other fixture's patch back and it stays for every later test of the worker.

Seen with `Hub.__init__`: `lock_order` (tests/lockorder.py, through `monkeypatch`) and `every_hub_settles_its_pusher` (through `own_patches`). `test_hub_place.py::test_a_reader_during_a_share_save_never_gets_the_page_rendered_from_the_private_folder` calls `monkeypatch.undo()`, `Hub.__init__` was left as `lockorder.hub_init`, and `test_hub_upgrade.py::test_a_second_signal_that_interrupts_the_first_inside_the_admit_lock_does_not_hang_the_hub` then failed with a `LockOrderViolation` (whole suite, 16 workers, on the sheaf-ci runners, 2026-11-20; reproduced serially on the CI runner host and bisected to that one test). PR 545 fixes this one pair by making `lock_order` ask for `every_hub_settles_its_pusher`, so the patches are laid and lifted in order.

## Where it can recur

The calls of `monkeypatch.undo()` in the tests (`grep -n "monkeypatch.undo()" tests/*.py`):

- `tests/test_hub_place.py:1035`, the test above; the only one of these in `LOCK_ORDER_SUITES`, fixed by PR 545 (merged 2026-11-22, merge a20013c9)
- `tests/test_hub_index_live.py:677`
- `tests/test_private_root_visible.py:1202`, `:1229`, `:1278`
- `tests/test_write_log.py:315`
- `tests/test_real_hub_untouched.py:18`, `:27`, `:58`: these test the behaviour itself and do not need changing

Not verified: whether any of the other files patches an attribute that an autouse fixture also patches.

## Fix to consider

Make `own_patches` skip the restore when the attribute no longer holds what `own_patches` set, or lay every patch of an attribute through one `MonkeyPatch` in the order they were made. Then drop the fixture argument added to `lock_order`.
