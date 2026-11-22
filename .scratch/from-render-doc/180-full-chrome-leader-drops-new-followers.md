# 180: In full Chromium the leader drops every new tab right after its join

**Claimed by:** Rumi

**Status:** done in #588 (merge 2983834c, head 60513fd8), CI green, review GO (round 1, provisional: Opus fallback, Codex at its usage limit)

**Priority:** high: it hits real users. In a real Chrome, only the leader tab gets live updates; every other tab of the browser gets none.

**Blocked by:** none

**From:** the probe for ticket 176, 2026-11-22

**Where (main 621e95aa):** `src/sheafmd/page/live.js`: the tab's own `navigator.locks.request('sheaf-tab-' + TAB)` at the top, `Source` (its first `ask({t: 'join'})`), `Leader.prototype.watching` (the comment at line 267 and the query after the grant)

## Observed

Chromium 145.0.7632.6 (Playwright chromium-1208), on the CI runner image, three tabs of one shared context (`new_context(..., shared=True)`), one document:

- **Full Chromium** (`chromium.launch(channel="chromium")`, the new headless mode) and **headed Chromium under Xvfb**: the hub counts **1** tab after 4 s, not 3. Each follower is joined and then left within a few milliseconds. The leader's journal reads `fetch /_/live/join POST` → `fetched 200` → `fetch /_/live/leave POST` for each follower's key, and no `{t: 'leave'}` from the follower ever crossed the BroadcastChannel. The followers send no leave of their own.
- **The headless shell** (`chromium.launch()`, what the page tests run on): the hub counts 3, as the tests expect. So CI does not see the bug.

The leave comes from the leader itself. A stack captured by wrapping `fetch` in the leader:

```
Error
    at window.fetch (<anonymous>:2:128)
    at send (http://127.0.0.1:30441/work/plan.md:664:14)   BODY {"stream":"23c0…","key":"7627…:1"}
```

The leader's `navigator.locks.query()` calls during the same 3 s, in order:

```
1. held:   sheaf-live (leader), sheaf-tab-841d… (leader)          pending: (none)
2. held:   sheaf-live (leader), sheaf-tab-7627… (follower), sheaf-tab-841d… (leader)
   pending: sheaf-live (follower)
```

At query 1 the follower had already joined, and its `sheaf-tab-7627…` lock was neither held nor pending.

## Cause

A follower requests its `sheaf-tab-<TAB>` lock and then posts its join on the BroadcastChannel. The two travel by different paths: the lock request goes to the lock manager, the message goes to the other tabs. In full Chromium the join reaches the leader first. `Leader.watching(tab)` then asks for `sheaf-tab-<tab>` and is granted it at once, because nobody holds it yet. Its query finds the lock neither held nor pending, and the leader drops the tab (`take({t: 'leave'})`). The comment in `watching` assumes the tab's own request is already queued when the leader's is granted. In full Chromium it is not. Once the follower's own request arrives it gets the lock, but nothing joins it again: it hears no change until it reloads.

## Proposed fix

A tab sends its first join only once its own `sheaf-tab-<TAB>` lock is granted: keep the promise of that grant and make `ask({t: 'join'})` (from `Source` and `rejoin`) wait on it. A leader that hears a join can then rely on the tab's lock being held. `watching` and its comment need no other change. Another option is to re-query after a short delay before dropping, but that keeps the race and only narrows it.

## Acceptance

- [x] A page test that runs in full Chromium (`channel="chromium"`, new headless) in CI: three tabs of one shared context, the hub counts 3 of 3, and a change on disk reaches a follower tab. `tests/page/test_page_shared_live_full_chromium.py`; red on the old `live.js` on t-compute ("timed out waiting for three tabs counted by the hub"), PASSED in CI on 60513fd8 (job 137379785797).
- [x] The existing shared-live tests still pass in the headless shell. All 10 of `tests/page/test_page_shared_live.py` PASSED in the same CI job.
