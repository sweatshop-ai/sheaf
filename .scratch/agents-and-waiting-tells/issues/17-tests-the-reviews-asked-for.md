# 17: Tests the reviews of #207 and #211 asked for

**What to build:** Tests only, no code change in `src/` unless a test finds a bug (then stop and write it up). Closes rows 9, 10 and 21.

**Where (main fac5160):**
- row 9: `tests/test_agent_tokens.py:119` is named `test_an_agents_row_has_no_display_which_the_previous_reader_requires_so_it_refuses_it` but checks the row has no `display` and that `verify` returns the client; nothing proves the previous reader refuses it
- row 10: `check_agent_names` has unit tests at `tests/test_agent_tokens.py:190-198`; the start through `hub/server.py:463-474` is covered for members vs tokens only (`tests/test_proxy_start.py:116`)
- row 21: `tests/test_hub_target.py` (28 tests) and `tests/page/test_page_target.py` hold none of: a second member's write beside the first, `update` with unchanged text, `resolve` of a resolved thread, a same-name re-made token for a member, the Change list after a key rotation (Playwright)

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session; if the Playwright test is slow or flaky, drop it to its own ticket and say so

- [ ] (9) rename the test to what it checks, or add the check it promises (the old row reader refuses a row without `display`)
- [ ] (10) a hub started with two agent tokens that sign one name stops with a `proxy-config` row, in loopback and with `[proxy]`; a hub started with a good table starts
- [ ] (21) five tests, one per case above, each failing when the code under it is broken (mutate once by hand, say so in the PR)
- [ ] Each test is under 5 s (main-only slow-test check)
