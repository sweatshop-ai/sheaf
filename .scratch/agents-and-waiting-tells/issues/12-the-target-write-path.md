# 12: The agent target: when a write announces it, what `/_/target` holds, and its shapes

**What to build:** A tab never keeps an old Agent line after an agent's write; `/_/target` holds the same place and reading guards as the other routes; and the target code loses the judgement calls #211 listed. Closes rows 18, 19 and 23 (#211).

**Where (main fac5160):**
- row 18: `mcp.py:336` `_agent_wrote`, called at `:647`, `:657`, `:789`, `:866`; the write is announced earlier in `_write`, `mcp.py:508` (`announce=True`)
- row 19: `hub/handler.py:1666-1679` `_target` goes through `_entry` and `targets.pick`, with no `place.held` and no `_reading` (compare `:1720`, `:1182`, `:1432`)
- row 23: `hub/targets.py:75` `agent_view` and `hub/core.py:636` `member_target` return tuples; the agent target is a bare dict; `targets.choices` imports `tell.who` locally at `hub/targets.py:98` (a cycle); the wire grammar `session | none | agent:<name>` is read in `targets.pick` (`:139-159`), `choices` (`:102`) and `page/page.js:166`

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session if row 23 is taken as two small moves only (the import cycle, the tuples → a small named type); anything more goes in a new ticket and the PR says so

- [ ] Test first (18): a tab fetches `/_/doc` the moment after an agent's `reply`; it already shows the new Agent line, and the event the tab got carries it (order: the target is set before `changed` is published, or `_agent_wrote` runs inside the same step)
- [ ] The write still stands when `note_write` raises (`target-failed` row), as today
- [ ] Test first (19): a sheaf closed between the check and the `/_/target` call; the member's own target is not stored and the answer is 404 as for any closed sheaf (9.11)
- [ ] `/_/target` takes the same hold as `/_/cancel` or `/_/comment`; the existing target tests stay green
- [ ] (23) `targets.choices` no longer imports inside the function: no import cycle between `targets` and `tell`
- [ ] (23) `member_target` / `agent_view` return a named type or a dataclass; every caller is changed, no behaviour is
- [ ] (23) the three places that know the wire grammar share one parse in Python; `page.js` keeps its own reading and a test names the grammar once for both
