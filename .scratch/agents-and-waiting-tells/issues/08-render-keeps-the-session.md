# 08: A render never drops the session a running Tell is kept on

**What to build:** `sheaf render --agent none`, or a render from another session, while a Tell runs must not drop or replace the kept session, so that Cancel stops the session that runs the Tell, never another and never none. Closes follow-up row 20 (#211, predates the ticket; Codex pass later on the whole list is row 1).

**Where (main fac5160):** `src/sheafmd/hub/core.py:781-783` `Hub.render`, `settle()`: `new.pop("session", None)` runs whenever a render carries a target. Cancel and `tell-stop-skipped` are in `hub/tell.py` and `hub/handler.py:1691` `_cancel`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session (core.py render + tell.py cancel + one test file)

- [ ] Test first: start a Tell on a document (fake session), then render the same file with `--agent none`; Cancel still stops that session and writes `tell-cancelled`, not `tell-stop-skipped`
- [ ] Test first: a render from a second session while the Tell runs; Cancel stops the first session
- [ ] A render with no Tell running still clears the kept session as it does today (D19, SPEC 8.3): the existing target tests stay green
- [ ] The page's target line after either render says what the hub now holds, and a Tell started afterwards goes where that says
- [ ] No other `pop("session")` or `session` overwrite in `hub/core.py` or `hub/targets.py` is left that a running Tell can meet (grep, list the hits in the PR)
