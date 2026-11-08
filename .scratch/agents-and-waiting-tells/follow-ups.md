# Review follow-ups of tickets 01–04 (PRs #210, #207, #211, #212) in one list

Every c and d finding and every "Codex pass later" item that the four PRs left open, merged where two PRs name the same thing. Read on 2026-11-07 from the PR bodies and the review-round comments; "Fixed in the stack" was checked against the code of #212's head e515777 (`/home/tiroir/Projects/sheaf-wt/t04-tells-that-wait`, package `src/sheafmd`).

**Reading the last column.** *Open (checked)*: I read the cited line at e515777 and the problem is still there. *Not checked*: I did not read the code; the PR text is the only evidence. *Fixed in the stack*: a later PR removed it.

No finding in the review-round comments was missing from the PR bodies; the comments only add the detail (round, citation) shown here. Merged duplicates: row 3 (#207 b + f), row 4 (#207 c + g), row 20 (#211 body + round 2 note + round 3 finding).

| # | PR | Class | Where | Follow-up | Already fixed by the stack? |
|---|----|-------|-------|-----------|-----------------------------|
| 1 | #210, #207, #211, #212 | Codex pass after 2026-11-11 | all four heads | Codex was out of tokens until 2026-11-11 08:36; every round ran as an Opus fallback. Run Codex on each head; its findings become tickets. | Open (not a code item) |
| 2 | #207 | c | `hub/proxy.py:436-456` `check_names` | Startup `check_names` misses old-token-vs-old-token and token-vs-person duplicates; only agent tokens are checked against every other token (`check_agent_names`). | Open (checked): `check_names` still compares members with tokens only |
| 3 | #207 | c | `hub/proxy.py:431`, `cli.py:880-881` vs `cli.py:900-907` | `check_names` folds names by `same_name` (case only), `add` by `name_key` (case, accent, width); switching could refuse a hub that starts today. Merged: #207 (b) and the second half of (f). | Open (checked): both functions still in use |
| 4 | #207 | c | `cli.py:884-890` `_proxy_table`, `cli.py:938` | `_proxy_table` swallows `ProxyError`, so `token add` / `list` sign with the person's name on a broken `[proxy]` table, while a running hub keeps its startup binding. Merged: #207 (c) and (g) third point. | Open (checked) |
| 5 | #207 | d | `hub/proxy.py:455` | A member named `action` (or a role word) makes the built signature `<client> (action)`, which SPEC 5.3 reads as a role. Only a member name that itself ends in `(action)` is refused. | Open (checked): no check on the built name |
| 6 | #207 | c | `cli.py:936-947`, `state.py:446-455` | Two concurrent `token add` runs can both pass the clash check. | Not checked |
| 7 | #207 | c | `hub/server.py:416` `_proxy_refused`, `hub/proxy.py:465-467` | A loopback refusal from `check_agent_names` is logged under the `proxy-config` label and its message offers "another member", which does not exist there. | Open (checked) |
| 8 | #207 | d | `hub/server.py:468` | `config.user_name()` runs once per token row at startup, so an unknown config key warns once per token. | Open (checked) |
| 9 | #207 | d | `tests/test_agent_tokens.py:119` | A test name promises more than it checks (`test_an_agents_row_has_no_display_...`). | Not checked |
| 10 | #207 | d | tests | No test starts the hub through `_run` to prove the start check. | Not checked |
| 11 | #210 | c | `hub/handler.py:1513` `_comment` | A comment body with a falsy `ask` (`false`, `0`, `""`) is accepted and ignored; only a truthy `ask` is refused. | Open (checked): `b.get("ask")` |
| 12 | #210 | d | `hub/tell.py:329` | Garbled docstring ("as for an a Tell begun by hand"); the cited line has moved from 319. | Open (checked) |
| 13 | #210 | d | `hub/handler.py:1529-1539` | Replace the `to_box = True` flag with `route == "box"`. | Open (checked) |
| 14 | #210 | d | `hub/handler.py:77`, `deliver.py:141-142` | "Ask was retired" is phrased twice; share one message. | Open (checked) |
| 15 | #210 | d | `hub/boxwait.py:41,57` | Drop the single-valued `kind` from `BoxWaits.add` and `Drop.kind` (the drop file's `kind: "tell"` stays). | Open (checked) |
| 16 | #210 | d | `page/page.css:52,72`, `page/page.js:1730` | Decide whether `rd-st-ask` / `rd-who-ask` are renamed (asset cache). | Open (checked) |
| 17 | #210 | d | history, commit 5f5a504 | Commit labelled WIP in the history. | Not a code item; cannot change without rewriting the branch |
| 18 | #211 | c | `mcp.py:335`, calls at 609, 619, 727, 793 | `_agent_wrote` runs after `changed` is published; a tab that fetches `/_/doc` in that window keeps the old Agent line until the next event. | Not checked (call sites still there) |
| 19 | #211 | c | `hub/handler.py` `/_/target` | `/_/target` takes no `place.held` / `_reading`; a sheaf closed in between stores the member's own target (reveals nothing). | Not checked |
| 20 | #211 | c | `hub/core.py:632-633` `render` | `sheaf render --agent none`, or a render from another session, while a Tell runs drops or replaces the kept session, so a Cancel stops the wrong session or none (`tell-stop-skipped`). Predates the ticket. Merged: PR body, round 2 note, round 3 finding. | Open (checked): `render` still does `new.pop("session")` |
| 21 | #211 | d | `tests/test_hub_target.py`, `tests/page/test_page_target.py` | Tests to add: a second member's write beside the first, `update` with unchanged text, `resolve` of an already resolved thread, a same-name re-made token for a member, the Change list after a key rotation (Playwright). | Not checked |
| 22 | #211 | d | `hub/handler.py` `/_/comment` | A member's `tell` comment on a non-box sheaf is refused with `PROXY_LINE` even with an agent target of their own. | **Fixed in the stack** (#212, checked): `to_agent` now lets it through, handler.py:1536 |
| 23 | #211 | d | `hub/targets.py`, `hub/tell.py` | Standards judgement calls: the agent target is a bare dict; `member_target` / `agent_view` return tuples; `member_target` and `Tell.view` envy `targets`; `targets.choices` imports `tell.who` locally (a cycle); the wire grammar `session | none | agent:<name>` is known in `targets.pick`, `choices` and `page.js`. | Not checked |
| 24 | #212 | c | `hub/waiting.py:188` and `:88` | `end()` passes an aggregate `seen` that overwrites the per-row value, so with two owners' Tells on one thread the other owner's toast can say "had already seen it" wrongly. | Open (checked): this is #212's own head |
| 25 | #212 | c | `hub/handler.py:1550-1560` | `/_/comment` re-checks the box or relay route (`still_visible`) only when `to_box` is set; a route appearing between check and write still queues for the agent. | Open (checked) |
| 26 | #212 | c | `comments.py:352` `next_id`, `hub/waiting.py:105-128` `watch` | A recycled thread id (max+1) can attach an old Tell to a new comment when the watcher has no entry for the document; store the comment's `at` / `by` in the row. | Open (checked) |
| 27 | #212 | c | `hub/waiting.py:195`, `hub/core.py:661` | `end_document` is never called; `forget_root` leaves the Tells of a forgotten root in `tells.json`. | Open (checked): only the definition exists |
| 28 | #212 | c | `hub/waiting.py:118` | `watch` reads the file without the document lock; a truncate-then-write editor caught mid-save ends the Tells for good. | Open (checked) |
| 29 | #212 | d | `hub/mcp.py:43`, `agents/prompts.py:20`, `hub/waiting.py:30` vs `hub/targets.py:23`, `hub/tell.py:399` | `instructions` and `prompts.tell_agent` wording differs from SPEC 12; the revoked line says "The agent", not the signed name; `tid` / `reason` are extra fields beside 9.8; reason `closed` covers resolved too; `GONE` duplicates `targets.REVOKED`; the `tid` / token pair is matched by hand in five places; the `Waiting` docstring and the `take()` signature are stale. | Partly checked: `GONE` duplicate and "The agent" line open; the rest not checked |
| 30 | #212 | — | SPEC line 935 | A member's `telling` also holds the 9.12 box drops. | Deferred to ticket 05 by the PR itself; not a fix in the stack |

**Counts.** 30 rows. 1 fixed in the stack (22). 18 open and checked in the code (2, 3, 4, 5, 7, 8, 11–16, 20, 24–28). 1 partly checked (29). 7 not checked (6, 9, 10, 18, 19, 21, 23). 3 are not code items (1, 17, 30).

## Rows to tickets

Settled on 2026-11-08 at origin/main fac5160 (tickets in `issues/`, 08–17). Rows marked open were re-read there; the lines in the tickets are those of fac5160, not of e515777. Rows 6, 9, 10, 18, 19, 21, 23 and 29 were "not checked" and are now checked: all are open.

| # | Ticket or outcome |
|---|-------------------|
| 1 | not a ticket (a Codex pass on each head after 2026-11-11 08:36; its findings become tickets then) |
| 2 | 13 |
| 3 | 13 |
| 4 | 14 |
| 5 | 13 |
| 6 | 14 (open: `cli.py:936-947` checks the clash outside `Tokens.add`'s lock, `state.py:446-455`) |
| 7 | 13 |
| 8 | 13 |
| 9 | 17 (open: `tests/test_agent_tokens.py:119`) |
| 10 | 17 (open: only unit tests of `check_agent_names`, `tests/test_agent_tokens.py:190-198`) |
| 11 | 11 |
| 12 | 15 |
| 13 | 15 |
| 14 | 11 |
| 15 | 15 |
| 16 | 15 |
| 17 | not a ticket (a WIP commit in the history of #210; it cannot change without rewriting the branch) |
| 18 | 12 (open: `_write` announces at `mcp.py:508`, `_agent_wrote` runs after at `:647`, `:657`, `:789`, `:866`) |
| 19 | 12 (open: `hub/handler.py:1666-1679` takes no `place.held` / `_reading`) |
| 20 | 08 |
| 21 | 17 (open: none of the five tests is in `tests/test_hub_target.py` or `tests/page/test_page_target.py`) |
| 22 | fixed (`hub/handler.py:1536`, as the table says) |
| 23 | 12 (open: `hub/targets.py:75`, `:98`, `hub/core.py:636`) |
| 24 | 09 |
| 25 | 09 |
| 26 | 09 |
| 27 | 10 |
| 28 | 10 |
| 29 | 16 (open: `hub/waiting.py:30` duplicates `hub/targets.py:23`, `hub/tell.py:399` says "The agent"; the rest is checked first in the ticket) |
| 30 | not a ticket (deferred to ticket 05 by #212; 05 is done (#213); whether it closed the line was not read here) |
