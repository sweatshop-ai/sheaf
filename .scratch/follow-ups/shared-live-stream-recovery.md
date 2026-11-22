# The shared live stream does not recover from four cases a native EventSource would

**What to build:** Review of PR #474 (Opus fallback, Codex out of tokens) found no serious defect and four minor ones, each a case where the shared stream (`page/live.js`, `hub/handler.py`, `hub/events.py`) does less than a native EventSource.

- [x] Switching members in one browser in proxy mode: the shared connection belongs to the first member until the proxy ends it (`proxy.STREAM_SECONDS`, 300 s), so the second member's joins get 404 `no such stream`, the page loops every 2 s and after 15 s shows "Hub unreachable" and disables Save. When a join is refused for a different owner, the leader reopens its connection. **Done:** PR #539, merged as 1e9d5630.
- [ ] `page/index.js` creates its stream once. A failed join POST (network error, 404 when the hub closed the shared stream at a rollover before the leader saw it, 429) becomes readyState 2 and the index stays on "Reconnecting to the hub…" for good. Document pages recover through `streamClosed`; the index needs the same.
- [x] `live.js` sends `leave` for all keys on `pagehide` even when `event.persisted` is true, and has no `pageshow` listener: a page restored from the back/forward cache reads as open while the leader has dropped it, and live updates stop silently. Whether a page holding a Web Lock and a BroadcastChannel enters that cache is not checked. **Done:** PR #539, merged as 1e9d5630 (rejoin on `pageshow`; Firefox and Safari not checked).
- [x] `Shared._poll` scans subscriptions from the first one that joined: a tab that receives events faster than the writer sends them delays the tabs that joined after it. A round-robin start index removes it. **Done:** PR #537, merged as 2df1f06b.

**Blocked by:** None.

**Status:** open
