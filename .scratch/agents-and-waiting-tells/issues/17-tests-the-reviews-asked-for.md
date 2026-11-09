# 17: Tests the reviews of #207 and #211 asked for

**What to build:** Tests only, no code change in `src/` unless a test finds a bug (then stop and write it up). Closes rows 9, 10 and 21.

**Where (main fac5160):**
- row 9: `tests/test_agent_tokens.py:119` is named `test_an_agents_row_has_no_display_which_the_previous_reader_requires_so_it_refuses_it` but checks the row has no `display` and that `verify` returns the client; nothing proves the previous reader refuses it
- row 10: `check_agent_names` has unit tests at `tests/test_agent_tokens.py:190-198`; the start through `hub/server.py:463-474` is covered for members vs tokens only (`tests/test_proxy_start.py:116`)
- row 21: `tests/test_hub_target.py` (28 tests) and `tests/page/test_page_target.py` hold none of: a second member's write beside the first, `update` with unchanged text, `resolve` of a resolved thread, a same-name re-made token for a member, the Change list after a key rotation (Playwright)

**Blocked by:** None (can start immediately)

**Status:** done-in-PR (sweatshop-ai/sheaf#234)

**Size:** one session; if the Playwright test is slow or flaky, drop it to its own ticket and say so

- [x] (9) renamed to `test_an_agents_row_stores_no_display_and_verify_gives_back_its_client`, docstring says it does not run the previous reader (`tests/test_agent_tokens.py:119`). Not a guard of the old reader: that code is gone.
- [x] (10) three tests through a real `python -m sheafmd hub` (`tests/test_proxy_start.py`, end of file): two agent tokens signing one name stop the start in loopback and with `[proxy]`, and a good table starts. The row's kind is `token-names`, not `proxy-config` (`_proxy_refused` labels a `TokenNamesError` that way, `hub/server.py:416`); the tests assert `token-names`. Guard, not red first: the check already worked; mutation below.
- [x] (21) five tests, all guards (green on main, each red under one hand mutation, run once each): second member beside the first (`targets = {}` in `_set`), `update` with unchanged text (`if before != text` -> `if True` in `mcp.py`), `resolve` of a resolved thread (status check -> `if True`), same-name re-made token for a member (`and r.id == raw.get("id")` removed in `targets.live`), Change list after a key rotation, Playwright (`rotate` that empties `docs`). The start check test (10) was mutated by removing `check_start_names` in `_run`: red.
- [x] Each test is under 5 s (slowest new one 0.5 s; `--durations` run) (main-only slow-test check)
