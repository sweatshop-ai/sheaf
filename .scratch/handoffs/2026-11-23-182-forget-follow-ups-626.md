# Ticket 182: forget_root follow-ups of #611, merged in #626

Status on 2026-11-23: PR #626 merged (merge e5bfe06f, head dce64431). Ticket lines 43 to 50 in
`.scratch/from-render-doc/182-codex-recheck-findings-batch-2.md` are ticked with the sha; line 48 is
not fixed and the ticket gives the reason.

## Changes

- `state.py`: `_Claims.watchers` is a set of writers; `watch(address, writer)`; `forget_texts`
  deletes through `_unlink` and in its `finally` drops only its own writer's claims; `rename`
  deletes the source's hashes that only its watchers claimed (no root store) and clears the record.
- `live.py`: `detach` is idempotent; `reattach` takes it back; `unwatch` ends the watch without
  deleting; `forget` clears `_detached_store` in a `finally`.
- `core.py`: `_let_go_root` detaches before `roots_mod.forget`; on failure it reattaches only while
  the registry still holds the root, else records `forget-failed` and goes on. `_forget_entries`
  catches each document's failure, records it, calls `unwatch`, and always publishes `gone`.
- `tests/conftest.py`: autouse `no_claims_left` empties `Versions._claims` around each test.

## Review

Matt's code-review (standards and spec) and boss_review rounds 1 (full) and 2 (`--since 985a31f0`),
both provisional GO by the Opus fallback: Codex was at its usage limit until 2026-11-24 12:39Z, so
Codex re-reviews before any deploy. Minors accepted on the PR, no change:

- `roots_mod.forget` raising after the registry let the name go leaves render settings or read
  state for a name another folder may take (main leaves the same, plus the entries attached).
- `unwatch` takes no document lock: a write under way when a forget failed before taking the lock
  can leave its text at the address, unrecorded (kept, never lost).

## Next

Lines 54 and 55 (follow-ups of #608: `loose.py` `drop` calls `forget_root` under the moves lock;
`handler.py` `_cancel` waits behind `outgoing._transfer`) touch the same `forget_root` area.
Tests: `PYTHONPATH=src:tests .venv/bin/python -m pytest -q -p no:cacheprovider
tests/test_hub_live.py tests/test_hub_index_live.py tests/test_hub_state.py` (238 pass).
