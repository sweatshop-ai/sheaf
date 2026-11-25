# 199: the render time limit of 198 D fails renders it should only delay (198 G and H)

**Claimed by:** Wilma (handed off at claim), then Mei

**Status:** done: merged in #673 (9384b5ff), CI run 45704548289 green; review: Opus fallback rounds 1 and 2, provisional GO (Codex out), so Codex re-reviews this head before a release

**Blocked by:** none

**From:** ticket 198, boxes G and H (round 2 of #669). The track's decision: both are regressions introduced by #669 and are fixed in a PR of their own.

**Where:** `src/sheafmd/_pandoc.py` (`budget`, `run`), `src/sheafmd/hub/core.py` (`Hub.render`), `src/sheafmd/hub/handler.py` (`/_/render`), `src/sheafmd/cli.py` (`sheaf open`), SPEC 3.2, CHANGELOG.

## Rules

These rules are set by the track. The code must follow them, and a failing test comes first for each.

- **G.** Time spent waiting for a lock (behind a save, a refresh or another render of the document) never counts against a pandoc run's 120 s. Only pandoc's own running time counts.
- **H.** When a render takes longer than `sheaf open` waits, no failed page is published. The render finishes and the page is served on the next open, as before #669. Only a pandoc error, or one pandoc run past its own 120 s, is a failure.
- The finding of #640 stays answered: `sheaf open` gets an answer from the hub before its own 130 s wait runs out.

## Design

The client's 130 s are counted on its own clock, which includes any lock wait in the hub, so the answer to the client and the pandoc time limit are separated:

- `_pandoc.budget()` is removed. Each pandoc run keeps its own 120 s (TIMEOUT), as before #669. No run is cut short because of other runs or because of a lock wait (G, H).
- `Hub.render` runs the render (locks included) in a worker thread and waits for it for at most an answer limit below the client's wait (for example `RENDER_TIMEOUT - 10`). Note: `place.held` must be taken inside the worker, as it is bound to the thread that holds it.
  - If the render is done, the answer is as today, with the worker's exception re-raised in the request thread.
  - If it is not done, the hub answers `{"ok": true, "doc", "url", "pending": true}`. The render goes on and publishes its page when it is done; a later `sheaf open` with the same settings serves it without a rebuild.
- `sheaf open` with `pending`: prints that the hub is still rendering the page and that the next `sheaf open` serves it, opens no browser, and exits non-zero (the page was not opened).
- SPEC 3.2 and the CHANGELOG line of 198 D are replaced to say this.

## Boxes

- [x] **G** A render queued behind a lock held longer than 120 s, whose own pandoc runs are fast, renders the page; nothing reports a timeout. Failing test first: hold the document's lock from another thread past a fake 120 s, then render.
- [x] **H** A render whose pandoc runs together pass the answer limit (2 x 70 s on a fake clock, each under 120 s) publishes the finished page and no failed one; the request answers `pending` before the limit; the next render with the same settings serves the page without a pandoc run. Failing tests first, in `tests/test_hub_index.py` and the CLI test of `sheaf open`.
- [x] **D test** The 198 D test is replaced: its fake pandoc returned an empty page, so it did not show which run was cut.
- [x] Remove `_pandoc.budget`, its use in `Hub.render`, and `_SPENT`. Keep 198 F (failed table readings are not cached).

## How it was done (#673)

- G: `test_a_render_behind_a_lock_held_past_120_s_renders_the_page_whose_own_pandoc_runs_are_fast`. On the old code it fails on the run limits (119.97 s instead of 120) and, with a fake clock moved during the lock wait, on "its runs share 120 seconds".
- H: `test_a_render_longer_than_sheaf_open_waits_answers_pending_and_publishes_the_finished_page`. No fake clock is used, because the hub's wait is a real thread wait. The answer limit `core.RENDER_ANSWER_WITHIN` is set to 0.5 s, and the fake pandoc runs are held until the request has answered. CLI: `test_a_render_still_going_when_the_hub_answers_opens_no_browser_and_says_the_next_open_serves_it` in `tests/test_cli_hub.py`, with the `pending` answer made on the client side (the hub of that test is another process).
- Added beyond the design: a `render-failed` row for a failure after `pending` (SPEC 15), with a traceback for a bug; `Entry.rebuild_due`, so a failed rebuild for new settings is rebuilt by the next render; a pending render's link-rule warnings go to the next open.
- Left as found: a first render of a document runs pandoc inside `Hub.entry` with the hub's lock held, so after a `pending` answer that lock stays held until pandoc ends (it did before #673 too, inside the request). Two opens of one document while a render is pending each start a worker; the second waits on the locks and serves the page.
