# 02: Agent tokens signed `Client (Member)`

**What to build:** The hub's person can make a token for one AI client acting for one member, and every reply that token writes is signed `<client> (<member>)`, built by sheaf, never typed (SPEC 9.7, D27; design decisions 4 and 5). `ChatGPT (Hans)` for Hans's ChatGPT token, `AI (Hans)` for the token a door uses when it does not know the client.

**Blocked by:** None (can start immediately)

**Claimed by:** Mikkel 2026-11-07 01:42

**Status:** done

- [x] `sheaf token add <name> --client <client> [--write]` makes an agent's token; `--client` and `--as` together are refused; the client is cleaned by the display-name rule, at most 40 characters, without parentheses (evidence: tests/test_agent_tokens.py: test_add_with_client_and_as_is_refused, test_the_client_is_cleaned_by_the_display_name_rule, test_a_client_that_is_empty_too_long_or_holds_a_parenthesis_is_refused; PR #207 head f24412c, CI run 42324593854 success)
- [x] The row stores `client` and no `display`; `add` prints the name it will sign with; `list` shows the client and that name (evidence: test_the_row_of_an_agent_stores_the_client_and_no_display, test_add_with_client_prints_the_name_it_signs_with_and_list_shows_client_and_name, test_add_says_the_name_a_member_gives_it)
- [x] A door reply with an agent's token is signed `<client> (<member name>)`, the member being the one whose `tokens` name the token; in loopback mode or with no member, the hub's person's name (evidence: test_a_reply_by_an_agent_of_a_member_is_signed_client_and_member, test_in_loopback_mode_an_agent_signs_with_the_hubs_person_and_never_as_the_bare_person, test_an_agent_no_member_names_signs_with_the_hubs_person)
- [x] Renaming the member in the config changes the signature after a restart (evidence: test_renaming_the_member_changes_the_signature_after_a_restart)
- [x] `add` refuses a client whose built name equals a member's name or another token's display (evidence: test_add_refuses_a_client_that_passes_for_a_member_by_case_accent_or_width and the hubs-person, built-name-vs-display and second-token variants; Codex rounds 1-2 added test_add_refuses_a_typed_display_that_is_the_name_an_agent_signs_with, test_an_old_token_named_like_a_client_does_not_block_that_agent, test_the_hub_refuses_to_start_when_an_agent_signs_a_name_another_token_signs)
- [x] Tokens made before (with `display`, no `client`) sign exactly as before and are never agents (evidence: test_a_token_made_before_agents_signs_as_it_always_did_and_is_no_agent)
- [x] Tests over the HTTP door: the signature per client, `AI (<member>)`, and an old token unchanged (evidence: the door tests above (ChatGPT, AI, old token))
