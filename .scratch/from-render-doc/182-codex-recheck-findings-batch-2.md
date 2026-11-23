# 182: Codex recheck findings, batch 2

**Status:** open; M, N and U merged in cfb0513e (#606, Arvid)

**Blocked by:** none

**From:** the second re-check of Codex NO-GO findings on merged PRs (2026-11-23, 02:21-03:07Z), triaged against main bd3a9333. None of these is in ticket 181. The triage note counts 21 findings (4 fixed, 17 open) but lists 15 open items, G to U, with 10 serious; those 15 are below. Letters continue from 181 (A to F).

One box per item. Red test first on main for each; an item that cannot be reproduced stays unticked with the reason.

## Open, serious

- [ ] **G** (from #486): the page save checks `_text_writable` (`handler.py:1427`) before `place.held` and the save lock, while the door sets the generated mark under the file lock (`mcp.py:1329`). A save let in before the mark lands after the rebuild. Re-check under the lock.
- [ ] **H** (from #487): the `/_/cancel` root compare and `waiting_tells.end` / `tell.cancel` are not atomic (`handler.py:2541-2547`). A forgotten root's page can cancel the same-id Tell of the root that took the name. Same theme as 181 A.
- [x] **I** (from #482): `edit.py:795` `table_is_taken` excludes tables with a backslash or shortcode, so `x<br>` followed by two NBSP loses the typed break. *(PR #607, head 87dc795c, GO + CI, not merged yet: review rounds 1 and 2 provisional GO by the fallback reviewer, Codex at its usage limit; CI run 45113267729 green. Red test first: `tests/test_edit_cell_breaks.py`, two tests red on main. A break in a cell of a table `_cell_breaks` does not take is now judged by `_ends_its_cell`, and Enter's cut beside a kept break goes. Not fixed, as on main: one no-break space after a break that ends bold text stays in the cell when the break goes.)*
- [x] **J** (from #492): `mcp.py:763-770`, a git failure or timeout leaves a queued Tell on that root undelivered (pending addresses outside the listing are never added). Fixed: a Tell that waits for the calling agent is judged in a pass of its own after the listing, so it is listed where git gave no answer, the time ran out or the limit was reached. Red first: `tests/test_hub_waiting.py::test_a_tell_on_a_git_root_that_git_cannot_answer_is_still_listed_to_its_agent` (on main the Tell was missing). *(merged: #610, b280b4de; head 6e68a871, CI green, round 2 provisional GO, Codex to re-review)*
- [x] **K** (from #492): the 100k cap is applied in `list_documents` before `_sees`, so visible or shared pages are skipped. Fixed: the walk is not capped by count (half the time left instead); the limit is spent on what the caller may see. Red first: `tests/test_private_root_visible.py::test_the_documents_count_limit_counts_only_what_the_caller_sees` (on main the hidden pages used up the limit). *(merged: #610, b280b4de; head 6e68a871, CI green, round 2 provisional GO, Codex to re-review)*
- [ ] **L** (from #491): `live.py:542` `forget_texts` by hash (`state.py:305-312`) can delete a version the replacement document stored with the same text.
- [x] **M** (from #508): `client.py:397`, an older hub that answers without a `reason` is taken as the client's own upgrade stop, and the client spawns a hub over the user's stop. Fixed with N: the command reads the old hub's exit row and starts or waits for none when it says `stop` or `signal` (`client.exit_reason`). Red first: `tests/test_hub_upgrade.py::test_an_older_hub_whose_answer_names_no_reason_is_not_restarted_over_the_stop_that_ended_it` (on main it spawned). *(merged: #606, cfb0513e; head f8c388e0, CI green, round 2 provisional GO, Codex to re-review)*
- [x] **N** (from #508): `client.py:492-493` calls `spawn_hub("upgrade")` after `wait_stopped` without checking why the hub stopped (a stop or a signal won). Fixed by the exit-row check above, with and without the service (under it only a `stop` ends the wait, since the unit starts a signalled hub again; before, the command waited UPGRADE_WAIT for a hub that would not come back); a hub that left no row (killed) is replaced as before. Red first: `tests/test_hub_upgrade.py::test_a_stop_that_wins_after_the_upgrade_stop_was_taken_starts_no_hub_behind_it` (on main it spawned). *(merged: #606, cfb0513e; head f8c388e0, CI green, round 2 provisional GO, Codex to re-review)*
- [ ] **O** (from #511): `handler.py:1871`, a rename and a tick to `Share with bob` in one save leaves the box ticked with no shared key, and bob gets a 404 (the names branch at `:1859` is never reached).
- [ ] **P** (from #496; serious per Codex, minor per triage): `core.py:1012` `_refreshed(e)` takes the document lock inside the hub lock.

## Open, minor

- [x] **Q** (from #486): `SPEC.md:1663-1667`, the door tool table omits `generated`. Fixed: `read`, `create` and `update` rows name `generated`.
- [ ] **R** (from #496): the rebuild on entry runs after the hub lock is released, so a `FileNotFoundError` follows only an outside-the-hub delete. The changed-after-gone case is already ticket 91 line 19.
- [x] **S** (from #492): the cap applies per source, so up to 2 x 100k rows can come back without `more`. Fixed: one limit and one `more` per list root, its private roots counted with it. Red first: `tests/test_private_root_visible.py::test_the_documents_count_limit_is_one_for_a_root_and_the_private_root_listed_under_it` (on main 6 rows came back and no `more`). *(merged: #610, b280b4de; head 6e68a871, CI green, round 2 provisional GO, Codex to re-review)*
- [x] **T** (from #504): `index.py:73` and `mcp.py:725` differ on the author name for unread (a person named Claude). Fixed: both read `Comment.last_by` (the `display` name, 5.3); red test in `tests/test_hub_index.py`.
- [x] **U** (from #508): `core.py:1888` `on_stop(reason)` uses the local reason, so the announcement can say upgrade while `stop_requested` is stop. Fixed in the receiver (`server.py` `HubServer.stop`): `hub-stopping` carries `stop_requested` as it stands when the first callback is told. A stop decided after `hub-stopping` went out cannot be told (it was the stream's last event); SPEC 8.4 says so. Red first: `tests/test_hub_upgrade.py::test_a_stop_decided_after_an_upgrade_stop_is_what_the_tabs_are_told_when_the_upgrade_s_callback_comes_first` (on main the tabs were told `upgrade`). *(merged: #606, cfb0513e; head f8c388e0, CI green, round 2 provisional GO, Codex to re-review)*

## Fixed on main

Checked on bd3a9333, not repeated above: #486 share 403 (`handler.py:1582`), #486 hub-key mark (`mcp.py:965`), #486 README Ask, #510 typed task offset (`edit.py:447`).

## Follow-ups from PR 606 (fix-pass review round 2, minor)

- [ ] `client.py:403-404` `ask_stop`: a hub that already answers `signal` as the reason in force makes the command fail at once, even under the service, which starts a signalled hub again (14.3). The exit-row check applies the service rule; this early exit does not. SPEC 8.4's "answered `stop` or `signal` … starts no hub" would follow.
- [ ] Under the service, a `signal` exit row reads the same for a stray SIGTERM (restarted) and a `systemctl stop` or logout (not restarted): the second now waits UPGRADE_WAIT and says "did not come back on the new version". Say so in the code comment and SPEC 8.4, or tell the two apart.
