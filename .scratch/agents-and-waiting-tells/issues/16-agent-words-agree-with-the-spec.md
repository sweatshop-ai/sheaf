# 16: The words an agent reads agree with SPEC 12 and 9.8

**What to build:** What the door tells an agent about a waiting Tell, and the revoked line, match the SPEC; the constants and the pair match that were written twice or five times are written once. Closes row 29 (#212; its checked half is `GONE` and "The agent", the rest is checked in this ticket first).

**Where (main fac5160):** `mcp.py:40-46` `INSTRUCTIONS`, `agents/prompts.py:20` `tell_agent`, `hub/waiting.py:30` `GONE` (same text as `hub/targets.py:23` `REVOKED`; `hub/tell.py:48` has an unrelated `GONE`), `hub/tell.py:399` (`REVOKED.format(agent="The agent")`), `hub/waiting.py:57` `Waiting` docstring and `:156` `take()` signature, extra fields `tid` / `reason` beside SPEC 9.8, the `tid` / token pair matched by hand.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session; the first step reads SPEC 12 and 9.8 against the five places and writes the list of differences in the PR before any edit

- [ ] Start with a list, in the PR: each difference of the row's text, open or not, with file:line at the head you branch from
- [ ] Test first: the revoked line for a Tell names the agent by its signed name, not "The agent"
- [ ] `waiting.GONE` is `targets.REVOKED` (one constant); no test text changes except where the SPEC does
- [ ] `instructions` and `tell_agent` carry the SPEC's words; a test compares them with the SPEC's quoted lines
- [ ] The `tid` / token match is in one helper; the `Waiting` docstring and `take()` signature are true
- [ ] A reason `closed` that also covers resolved is either split or the SPEC line says it covers both; the PR says which
