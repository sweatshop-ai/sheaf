# 05: On the proxy socket a member Tells their own agents

**What to build:** A member signed in through the front (Open WebUI) can Tell their own agents from the page, and sees nothing of the hub account's session or of another member's agents (SPEC 9.9). This is what lets Hans send a comment to `ChatGPT (Hans)` from the ThinkingToo hub.

**Blocked by:** 04 (A Tell to an agent waits on the document)

**Claimed by:** Birgit 2026-11-07 07:17

**Status:** done

- [x] On the proxy socket `/_/tell`, `/_/cancel` and `/_/target` serve the member's own agents only; `/_/jump` still answers 404 (tests/test_proxy_own_agents.py first three tests; tests/test_proxy_socket.py NOT_HERE has /_/jump)
- [x] A comment with `tell` goes to the member's own agent, or to James's window or a fork's relay where 9.12 and 9.14 send it, else 400 with the 10.6 line (tests/test_hub_waiting.py::test_a_members_tell_waits_for_their_own_agent_only, ::test_the_box_or_a_relay_comes_before_a_members_agent, ::test_a_member_with_no_agent_of_theirs_is_refused_the_tell_route_with_the_line_of_10_6)
- [x] `telling` and the document stream carry only the member's own waiting Tells and drops; nothing of the hub account's session or of another member's agents (tests/test_hub_work.py::test_a_members_telling_holds_their_own_drop_for_james_and_no_other_members, ::test_a_delivered_drop_turns_the_orange_of_the_member_who_sent_it_and_no_other_members, ::test_a_members_drop_that_fails_tells_their_index_while_another_members_drop_still_works; tests/test_hub_waiting.py::test_each_page_is_told_of_its_own_tells_only)
- [x] A member never can pick, see or cancel another member's agent, and never the hub account's session (tests/test_hub_target.py::test_a_member_cannot_pick_another_members_agent_nor_the_hub_accounts_session; tests/test_hub_waiting.py::test_a_members_cancel_ends_only_their_own_tell_and_the_hub_persons_cancel_leaves_it)
- [x] Tests on the proxy socket: two members with an agent each, each sees and controls only their own (tests/test_proxy_own_agents.py, 8 tests, two members with an agent each). PR sweatshop-ai/sheaf#213 head b12ece3, CI run 42351264725 success; Opus-fallback reviews: round 2 NO-GO fixed, round 3 GO.
