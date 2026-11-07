# Handoff: Task #02, agent tokens (Mikkel, 2026-11-07)

- Worktree `/home/tiroir/Projects/sheaf-wt/t02-agent-tokens`, branch `mikkel/02-agent-tokens`, draft PR #207 to main, based on #205 (merge after it).
- Head pushed: `cc26a34` (contains origin/main 735e100 and #205 tip e377485). Superseded run 42320575555 (on 9dcf232) was cancelled by me. A new run starts from cc26a34: check `gh api repos/sweatshop-ai/sheaf/commits/<sha>/check-runs -q .total_count` first, zero means nothing ran.
- Done: code, 38 tests in `tests/test_agent_tokens.py` (169+ with test_cli_token, test_tokens pass), code-review (once, done: do not rerun), security-review (nothing at confidence 8+), token id (Runa's decision 1), PR body with follow-ups (a to e).
- Not fixed on purpose: (b) `same_name` to `name_key` in `check_names`, because it can refuse a hub that starts today.

## Remaining
1. Wait for CI green on the head.
2. Codex rounds 1 to 3 (SENSITIVE PR, at most 3): `/codex-review`, output to a file, post on PR #207 as "Codex review N (run by Mikkel)", every citation VERIFIED or NOT FOUND, reply to each finding, fix class a/b. Batch fixes, push once, cancel your own superseded runs. Over 500 added lines: tell Runa first (now about 350).
3. Tick the boxes in `/home/tiroir/Projects/sheaf-wt/spec-205/.scratch/agents-and-waiting-tells/issues/02-agent-tokens.md` with the evidence below, set Status `done`, commit that file by path only (`git -C .../spec-205 status` first). Do not touch the Claimed-by line.
4. Report to Runa (uds address of her latest message). Thierry merges.

## Box to evidence (all in `tests/test_agent_tokens.py`; run `uv run pytest tests/test_agent_tokens.py -q -p no:xdist`)
- Add/refusals/cleaning: `test_add_with_client_and_as_is_refused`, `test_the_client_is_cleaned_by_the_display_name_rule`, `test_a_client_that_is_empty_too_long_or_holds_a_parenthesis_is_refused`.
- Row stores `client`, no `display`; add prints name; list shows client and name: `test_the_row_of_an_agent_stores_the_client_and_no_display`, `test_add_with_client_prints_the_name_it_signs_with_and_list_shows_client_and_name`, `test_add_says_the_name_a_member_gives_it`.
- Door signature, loopback, unbound: `test_a_reply_by_an_agent_of_a_member_is_signed_client_and_member`, `test_in_loopback_mode_an_agent_signs_with_the_hubs_person_and_never_as_the_bare_person`, `test_an_agent_no_member_names_signs_with_the_hubs_person`.
- Rename after restart: `test_renaming_the_member_changes_the_signature_after_a_restart`.
- Collisions: `test_add_refuses_a_client_that_passes_for_a_member_by_case_accent_or_width`, `..._for_the_hubs_person`, `..._whose_built_name_is_another_tokens_display`, `test_add_refuses_a_second_token_that_would_sign_the_same_name`.
- Old tokens: `test_a_token_made_before_agents_signs_as_it_always_did_and_is_no_agent`.
- Tests over the HTTP door: the door tests above (ChatGPT, AI, old token).
- Token id: `test_every_new_token_gets_a_random_id_...`, `test_revoking_a_token_and_adding_one_of_the_same_name_gives_a_different_id`.

## P17
`uv run python -c 'import sheafmd; print(sheafmd.__file__)'` gave `/home/tiroir/Projects/sheaf-wt/t02-agent-tokens/src/sheafmd/__init__.py`. No dev hub was run; tests use the in-memory handler. Re-prove it in the new session before trusting a run.

## Traps
- `sleep` in the foreground is blocked; wait with Monitor/run_in_background.
- Test for a config file needs `paths.config_file().parent.mkdir(...)` first.
- The old `TokenRow` equality asserts now use `dataclasses.replace(..., id=None)` because rows carry an id.
- Hub person in tests is `Ada` (SHEAF_NAME); proxy fixtures set `hub.proxy` after the hub is built.
- Load is above 8: run only the test files you touch.
