# 199: the render time limit of 198 D fails renders it should only delay (198 G and H)

**Claimed by:** Wilma (handed off at claim, see .scratch/handoffs/2026-11-25-199-render-budget-regressions.md)

**Status:** open (claimed, design written, no code yet)

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

- [ ] **G** A render queued behind a lock held longer than 120 s, whose own pandoc runs are fast, renders the page; nothing reports a timeout. Failing test first: hold the document's lock from another thread past a fake 120 s, then render.
- [ ] **H** A render whose pandoc runs together pass the answer limit (2 x 70 s on a fake clock, each under 120 s) publishes the finished page and no failed one; the request answers `pending` before the limit; the next render with the same settings serves the page without a pandoc run. Failing tests first, in `tests/test_hub_index.py` and the CLI test of `sheaf open`.
- [ ] **D test** The 198 D test is replaced: its fake pandoc returned an empty page, so it did not show which run was cut.
- [ ] Remove `_pandoc.budget`, its use in `Hub.render`, and `_SPENT`. Keep 198 F (failed table readings are not cached).
