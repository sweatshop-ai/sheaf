# 14: `sheaf token add` refuses on a broken `[proxy]` table, and two adds cannot clash

**What to build:** `token add` and `token list` stop signing with the person's name when the `[proxy]` table is broken, and two concurrent `token add` runs cannot both pass the name-clash check. Closes rows 4 and 6 (#207).

**Where (main fac5160):**
- row 4: `cli.py:884-890` `_proxy_table` catches `ProxyError` and returns none; used at `cli.py:938`, `:959`, `:985`
- row 6: `cli.py:936-947` runs `_agent_clash` before `tokens.add`; `hub/state.py:446-455` `Tokens.add` checks only the token's own name under `tokens.lock`

**Blocked by:** None (can start immediately)

**Status:** done-in-PR #231

**Size:** one session (cli.py, state.py, tests/test_cli_token.py)

- [x] Test first (4): a broken `[proxy]` table (a missing key); `token add --client` fails with the table's error and writes nothing; `token list` says the table is broken instead of listing names signed for the person
  - Evidence: tests/test_agent_tokens.py `test_add_a_client_refuses_with_the_tables_error_and_writes_nothing_while_the_proxy_table_is_broken` (red first: `add` signed with the person); `test_list_says_the_table_is_broken_and_names_no_signature_built_on_the_person` (red first), `test_list_without_a_proxy_table_still_signs_an_agent_with_the_person` (guard)

- [x] A running hub keeps its startup binding (unchanged; one test says so)
  - Evidence: `test_a_running_hub_keeps_the_binding_it_started_with_while_the_table_is_broken_on_disk` (a guard, passes before and after: the hub reads the table once at the start)

- [x] Test first (6): two `token add --client` for the same client and member run at once (two processes, or the clash check called inside a held `tokens.lock`); exactly one is written, the other fails with the clash message
  - Evidence: `test_two_adds_of_one_client_and_member_at_once_write_exactly_one`: two real processes, both stopped at `tokens.lock` held by the test; red first (2 written), now 1 written and the other exits 1 with the clash message

- [x] The clash check runs inside `Tokens._locked()`, with the bindings of the day passed in; the CLI text stays as today
  - Evidence: `Tokens.add(..., clash=)` calls the check under `_locked()` with the rows of that moment, the CLI passes a closure over the bindings it read; `test_the_clash_check_of_add_runs_inside_the_lock_with_the_rows_of_that_moment`; `test_the_clash_message_of_add_is_the_one_it_always_was` pins the text

- [x] No lock is held across the config read
  - Evidence: `test_the_config_is_read_before_the_lock_is_taken`: `config.user_name()` runs with no lock held (the table is read in the CLI before `add` is called)
