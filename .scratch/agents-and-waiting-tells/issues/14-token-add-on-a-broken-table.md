# 14: `sheaf token add` refuses on a broken `[proxy]` table, and two adds cannot clash

**What to build:** `token add` and `token list` stop signing with the person's name when the `[proxy]` table is broken, and two concurrent `token add` runs cannot both pass the name-clash check. Closes rows 4 and 6 (#207).

**Where (main fac5160):**
- row 4: `cli.py:884-890` `_proxy_table` catches `ProxyError` and returns none; used at `cli.py:938`, `:959`, `:985`
- row 6: `cli.py:936-947` runs `_agent_clash` before `tokens.add`; `hub/state.py:446-455` `Tokens.add` checks only the token's own name under `tokens.lock`

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session (cli.py, state.py, tests/test_cli_token.py)

- [ ] Test first (4): a broken `[proxy]` table (a missing key); `token add --client` fails with the table's error and writes nothing; `token list` says the table is broken instead of listing names signed for the person
- [ ] A running hub keeps its startup binding (unchanged; one test says so)
- [ ] Test first (6): two `token add --client` for the same client and member run at once (two processes, or the clash check called inside a held `tokens.lock`); exactly one is written, the other fails with the clash message
- [ ] The clash check runs inside `Tokens._locked()`, with the bindings of the day passed in; the CLI text stays as today
- [ ] No lock is held across the config read
