# 185: Codex recheck findings, batch 4

**Status:** open

**Blocked by:** none

**From:** the fourth re-check of Codex NO-GO findings on merged PRs (2026-11-23, afternoon). It covers 5 PRs (#537 #543 #545 #548 #549) and the highest review round of each (round 7, 5, 12, 5 and 5). Triaged against main 2f8620d3. Letters continue from 183 (V to BC): BD to BI, in PR order.

**Counts:** 6 findings:

- 4 still present: 0 serious, 4 minor (fixed in #624).
- 1 filed later: BJ, a flaky test seen in #624's CI.
- 2 already fixed on main.
- 0 already filed.
- 0 not a defect.

Codex marked 5 of the 6 serious; the ratings below are the triage's own, by the rule of 183. Serious means a wrong result in ordinary use, a crash, data loss, or a security or privacy breach. Minor means the defect needs a narrow race, a malformed answer from a peer, or an unusual name, or it changes only a status code, a log row or the form of the source.

**Where (open items):** `src/sheafmd/hub/events.py` (BD), `.github/workflows/ci.yml` with SPEC 18 (BF), `tests/test_hub_tell.py` (BG), `src/sheafmd/send.py` (BH).

Each open item has one box. Write a red test on main first for each. If an item cannot be reproduced, leave its box unticked and give the reason.

## Open, serious

None.

## Open, minor

- [x] **BD** (from #537): `Subscription.put` (`hub/events.py:51-52`) reads `self.on_put` twice: once for the `is not None` check, once for the call. `Shared.leave`, a replacing `join` and `Shared.close` set it to `None` from another thread (`events.py:166`, `:173`, `:230`). A clear between the two reads calls `None()`. The `TypeError` leaves `Bus.publish` (`events.py:109-110`, no guard), so the subscribers after that one in the list miss the event, and the thread that published gets the error. It needs a tab that leaves during a publish. Read the callback once into a local, then check and call it.
- [x] **BF** (from #545): `ci.yml:69` sends a pull request from a fork to GitHub's runners, but the workflow a fork's pull request runs is the fork's own, so a fork can change that line. The comment at `ci.yml:65-68` says the repository setting "all external contributors" is what holds a fork's run until someone reads it. GitHub's setting exempts members of the organization. A member who has no write access to the repository could therefore run code on the self-hosted `sheaf-ci` runners without approval. The runner group `sheaf-public` is not restricted to selected workflows. Latent today: the organization's base permission is read, and each of its members is an admin of this repository, so no member gains more than their own push already gives. Correct the comment and SPEC 18 to say that a member of the organization is trusted with the runners, or set the approval policy to cover every fork pull request, before a member without write access joins.
- [x] **BG** (from #545): `test_the_page_never_holds_the_session_id_the_socket_or_the_command` (`tests/test_hub_tell.py:252`) compares how often the pid stands alone in the page and the `/_/doc` answer with and without a session. A session that both adds the pid once and removes another occurrence of the same number (a count or a status code that changes with the session) passes. The test then no longer proves that the pid never reaches either answer. Compare the occurrences by place (the text around each), or give the session a pid that no page text can hold.
- [x] **BH** (from #548): `pull` re-reads the file (`send.py:643`) and then calls `write_text_atomic` (`send.py:645`) without `check=`. An edit saved while the temporary file is written and synced is replaced by the shared Sheaf's text, and the edit is lost. `write_text_atomic` already takes a `check` callable that runs just before the rename (`atomic.py:11-17`). Pass the hash comparison there and raise `_leave_theirs` from it.

Ticked BD, BF, BG and BH: merged in #624 (merge e9abcfae, head bb741e89). BD: `Subscription.put` reads `on_put` once and `Bus.publish` records `publish-failed` and goes on (`tests/test_hub_events_bus.py`). BH: `pull` passes `check_unchanged` to `write_text_atomic` (`test_pull_never_overwrites_an_edit_saved_while_it_writes_the_file`). BG: `number_places` in `tests/helpers.py` compares the pid by place. BF: the `ci.yml` comment and SPEC 18 say a member of the organisation is trusted with the runners, and what to change before a member without write access joins.

- [ ] **BJ** (from #624's CI, run 45194438767): `tests/test_repo_pages.py::test_a_slow_clone_never_holds_a_report_and_one_repo_does_not_hold_another` (`test_repo_pages.py:719`) asserts that a report comes back within 0.5 s of `time.monotonic()`. Under 16 workers on the shared runner one took 0.636 s and the job failed; the re-run of the failed job passed. The house rule (SPEC 18) has a test that times computation read `time.process_time()`; wall time stays only where a real timeout is the point. Make the check not depend on wall time under load: for example, have the slowed `_clone` block on an event the test sets only after `report_once` has answered, so an answer that waited for the clone cannot come back at all.

## Already filed

None.

## Already fixed on main

- **BE** (from #543): an expired in-memory pin was read again from the versions store, whose pins were pruned only at hub start. Fixed in a218bf1b (ticket 137): `Versions.get` skips a pin file older than `PINS_MAX_AGE` (`hub/state.py:297-301`), so `_known` (`hub/live.py:185-187`) no longer finds it.
- **BI** (from #549): `_own_merge` returned `None` when `pieces` was empty, so a region where the file deleted one split line and the page deleted the rest came back through the fallback merge with the file's deleted line. Fixed in fe75ec79 (ticket 137): an empty `pieces` deletes the region unless a comment is in it (`edit.py:3168-3171`). Test: `tests/test_edit_137_followups.py::test_a_line_the_file_deleted_stays_deleted_when_the_edit_leaves_nothing_else`.

## Not a defect

None.
