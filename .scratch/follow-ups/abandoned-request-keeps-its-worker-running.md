# An abandoned request keeps its worker thread running

**What to build:** Stop computing a response when the caller has closed the connection.

**Blocked by:** None. Most valuable after #459, but not dependent on it.

**Status:** done

## Problem

`src/sheafmd/hub/server.py:123` hands the handler `gone=self._gone` (defined at `:146`, a zero-timeout `select` on the connection), but `sheaf_view.data` never calls it. The response is built to the end and only `res.body` is written at `:139`, where the write fails (BrokenPipeError). A browser that reloads or navigates away therefore leaves a thread computing a listing nobody will read. On a production hub a listing took 48-51 s, so each reload during the slow window added a second 50 s job.

## Evidence

- The reverse proxy's access log of a production hub (2026-11-19) shows two client-abandoned requests (status 0) of 37.9 s and 43.0 s on `/_/mount?sheaf=1`.
- The hub journal has a BrokenPipeError at 02:19:43Z the same night.

## Acceptance criteria

- [x] A test starts a listing request, closes the client socket, and asserts the handler stops within one checkpoint (counts the pages visited after the close, bounded). `tests/test_hub_abandoned.py::test_a_caller_that_closes_the_connection_ends_the_run_and_logs_no_broken_pipe` (#505, e2df41e4): a real socket closed with a reset, fewer than 20 pages read; the in-memory stop is `tests/test_hub_sheaf.py::test_a_listing_whose_caller_has_gone_stops_reading_pages` (#461, 5a5a8a30)
- [x] The listing loop checks `gone()` at each root and every 8 pages (`sheaf_view.CHECK_EVERY`) and ends with a 499 (#461, 5a5a8a30; the channel read in #464, 2863a308)
- [x] No BrokenPipeError is logged for an abandoned listing: the 499 written to the closed socket is dropped quietly in `server.py` (#505, e2df41e4), same test as box 1
- [x] A normal request is unchanged: CI green on #461, #464 and #505
