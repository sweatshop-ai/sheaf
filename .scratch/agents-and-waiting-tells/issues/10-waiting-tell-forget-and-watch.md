# 10: Waiting Tells: a forgotten root ends its Tells, and `watch` reads under the lock

**What to build:** A root that is forgotten takes its waiting Tells with it, and the watcher never ends a Tell because it caught a document mid-save. Closes rows 27 and 28 (#212).

**Where (main fac5160):**
- row 27: `hub/waiting.py:195` `end_document` has no caller (grep); `hub/core.py:799` `forget_root`
- row 28: `hub/waiting.py:109-121` `watch` calls `rdc.parse(e.read())` (`:118`) without the document lock; the hub's lock is `place.held(hub, address)` as used at `hub/handler.py:1182`

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session (waiting.py, core.py, one test file)

- [ ] Test first (27): a Tell waits on a document, `forget_root` runs for its root; `tells.json` holds no row of that root, the page gets `tell-cancelled` (reason says the folder was forgotten) and a diagnostics row is written
- [ ] Other roots' Tells are untouched by that forget, also those of the same token
- [ ] Test first (28): the file is truncated and then written by an editor while `watch` runs (hold the file in the truncated state with the document lock); the Tell is not ended; after the write completes, the next pass sees the thread and keeps it
- [ ] `watch` takes the document lock, or rereads once after an empty or unparsable read before it ends anything; the PR says which and why
- [ ] A thread that really is gone still ends its Tell at the next pass (the existing test for a thread closed from outside stays green)
