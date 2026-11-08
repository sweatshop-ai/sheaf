# 08: A render never drops the session a running Tell is kept on

**What to build:** `sheaf render --agent none`, or a render from another session, while a Tell runs must not drop or replace the kept session, so that Cancel stops the session that runs the Tell, never another and never none. Closes follow-up row 20 (#211, predates the ticket; Codex pass later on the whole list is row 1).

**Where (main fac5160):** `src/sheafmd/hub/core.py:781-783` `Hub.render`, `settle()`: `new.pop("session", None)` runs whenever a render carries a target. Cancel and `tell-stop-skipped` are in `hub/tell.py` and `hub/handler.py:1691` `_cancel`.

**Blocked by:** None (can start immediately)

**Status:** done-in-PR (sweatshop-ai/sheaf#223)

**Size:** one session (core.py render + tell.py cancel + one test file)

- [x] Test first: start a Tell on a document (fake session), then render the same file with `--agent none`; Cancel still stops that session and writes `tell-cancelled`, not `tell-stop-skipped`
  - Evidence: `tests/test_hub_tell.py::test_a_render_with_agent_none_while_a_tell_waits_leaves_the_session_to_stop` (red at 6d2bd07's parent, green after): the Cancel returns ok, writes `tell-cancelled` with `sent: true`, the session's peer receives the stop message, and no `tell-stop-skipped` row is in the diagnostics
- [x] Test first: a render from a second session while the Tell runs; Cancel stops the first session
  - Evidence: `tests/test_hub_tell.py::test_a_render_from_a_second_session_while_a_tell_waits_leaves_the_first_to_stop` (red, then green): the target is s-2 after the render, and the stop message reaches s-1's socket (s-2's socket does not exist)
- [x] A render with no Tell running still clears the kept session as it does today (D19, SPEC 8.3): the existing target tests stay green
  - Evidence: `test_a_render_with_no_tell_running_clears_the_session_and_keeps_none_beside_the_new_one` and the existing target tests (`test_a_render_from_a_session_takes_the_target_back_from_an_agent`, `test_a_render_with_no_agent_keeps_an_agent_target_and_none_clears_everything`) stay green: `tests/test_hub_target.py` and `tests/test_hub_tell.py`, 166 passed locally, none skipped or xfailed
- [x] The page's target line after either render says what the hub now holds, and a Tell started afterwards goes where that says
  - Evidence: `test_a_render_while_a_tell_runs_keeps_the_session_it_was_sent_to_beside_the_new_target` asserts `hub.target(DOC)` is None / s-2 (what the page's target line shows) and `hub.target(DOC, kept=True)` is s-1; `test_a_session_kept_for_a_cancelled_tell_is_gone_when_the_next_tell_starts`, `test_a_cancel_of_a_tell_started_after_the_first_one_ended_stops_the_target_not_the_kept_session` and `test_a_comment_sent_with_tell_after_the_first_tell_ended_drops_the_kept_session_too` show a Tell started afterwards goes to, and is stopped at, the target. Limit left open: two Tells of different threads at once share one kept slot (see the PR)
- [x] No other `pop("session")` or `session` overwrite in `hub/core.py` or `hub/targets.py` is left that a running Tell can meet (grep, list the hits in the PR)
  - Evidence: grep of `session` writes in `hub/core.py` and `hub/targets.py` at the PR head: `core.py:828` render `pop` (now keeps the told session, `:830`); `core.py:761-763` `drop_kept` (pop or store, only when no other Tell is live); `targets.py:136-137` `_set` (does not overwrite a session kept for a live Tell); `targets.py:163` `pick("session")` pop (returns early when the target is already that session). Reads: `core.py:727-728`, `:772`, `targets.py:69`. No other write is left that a running Tell can meet
