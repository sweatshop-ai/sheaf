# An abandoned request keeps its worker thread running

**What to build:** Stop computing a response when the caller has closed the connection.

**Blocked by:** None. Most valuable after #459, but not dependent on it.

**Status:** ready

## Problem

`src/sheafmd/hub/server.py:123` hands the handler `gone=self._gone` (defined at `:146`, a zero-timeout `select` on the connection), but `sheaf_view.data` never calls it. The response is built to the end and only `res.body` is written at `:139`, where the write fails (BrokenPipeError). A browser that reloads or navigates away therefore leaves a thread computing a listing nobody will read. On a production hub a listing took 48-51 s, so each reload during the slow window added a second 50 s job.

## Evidence

- The reverse proxy's access log of a production hub (2026-11-19) shows two client-abandoned requests (status 0) of 37.9 s and 43.0 s on `/_/mount?sheaf=1`.
- The hub journal has a BrokenPipeError at 02:19:43Z the same night.

## Acceptance criteria

- [ ] A test starts a listing request, closes the client socket, and asserts the handler stops within one checkpoint (counts the pages visited after the close, bounded).
- [ ] The listing loop (`Index.data`, `core.py` `visible` loop) checks `gone()` at least once per page batch and returns early without a raise that logs as an error.
- [ ] No BrokenPipeError is logged for an abandoned listing.
- [ ] A normal request is unchanged (existing tests pass; touched test files only on the laptop, the rest in CI).
