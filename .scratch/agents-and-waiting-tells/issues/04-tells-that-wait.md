# 04: A Tell to an agent waits on the document

**What to build:** When the target is an agent (ChatGPT, Claude.ai, the Open WebUI assistant), Tell no longer needs a running session: the Tell waits on the document until that agent next calls `documents`, which hands it over with the whole message; the agent acts and replies with role `action`, which ends it (SPEC 9.8, 10.5, 12; D26; design decision 6).

**Blocked by:** 03 (The target is a session or an agent, and the person can change it)

**Claimed by:** Naya 2026-11-07 05:18

**Status:** done

- [x] Tell (button or comment with `tell`) to an agent target writes the comment and records a waiting Tell in the state folder; it survives a hub restart and has no expiry — test_a_tell_to_an_agent_waits_is_listed_first_and_ends_on_its_action_reply, test_a_comment_sent_with_tell_writes_it_and_the_tell_waits, test_a_tell_survives_a_real_restart_of_the_hub_process (subprocess hub; no expiry)
- [x] `documents` with that agent's token lists the document first, even with no other open comment, with `tells` holding the Tell's message; no other token, and no other member's agent, ever sees it — test_a_tell_to_an_agent_waits_is_listed_first…, test_a_token_never_sees_the_tell_of_another…, test_a_members_tell_waits_for_their_own_agent_only; `tells: []` when none wait (SPEC 12) in every documents assertion
- [x] The first listing marks it seen (`tell-seen`); listing again changes nothing — test_a_tell_to_an_agent_waits_is_listed_first… (tell-seen once; listed again changes nothing)
- [x] It ends and is never listed again on that token's `action` reply in the thread (`tell-done`), on a resolve or delete of the thread, on Cancel from the page (`tell-cancelled`), and when the token is revoked — test_a_tell_to_an_agent_waits_is_listed_first… (action reply), test_resolving_or_deleting_the_thread_ends_the_tell (door resolve, page resolve, page delete), test_a_cancel_from_the_page_ends_it_and_says_whether_the_agent_had_seen_it, test_revoking_a_token_ends_its_tells… and test_a_revoke_by_the_cli_ends_the_tell_at_the_watchers_next_pass… (ends at the watcher's pass, no page asking), test_a_thread_closed_from_outside_ends_the_tell_at_the_watchers_next_pass (CLI/hand edit)
- [x] A second Tell to the same agent on the same thread while one waits is refused 409 with the SPEC's line; a reply sent with it is still written — test_a_second_tell_to_the_same_agent_on_the_thread_is_refused_and_a_reply_sent_with_it_is_written
- [x] The page shows "Waiting for <agent>…", then "<agent> has seen it…", with Cancel, across a reload and a restart; no orange dot and no upgrade block for a waiting Tell — tests/page/test_page_waiting_tell.py (3: waiting, has seen it, Cancel, reload; no spinner), test_a_waiting_tell_gives_no_orange_dot_and_does_not_hold_an_upgrade_back
- [x] The door's `instructions` tell the agent to call `documents` first — test_the_instructions_tell_the_agent_to_call_documents_first
- [x] Each step writes its diagnostics row (queued, seen, done, cancelled) with the token's name and never the text — test_each_step_writes_a_row_with_the_tokens_name_and_id_and_never_the_text
- [x] Tests: the full loop over the HTTP door with a fake agent token; restart in between; isolation between two tokens; page lines (Playwright) — tests/test_hub_waiting.py (28), tests/page/test_page_waiting_tell.py (3): loop, restart, isolation (tokens, members, event streams: test_each_page_is_told_of_its_own_tells_only), page lines
