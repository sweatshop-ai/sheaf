# 12: The agent target: when a write announces it, what `/_/target` holds, and its shapes

**What to build:** A tab never keeps an old Agent line after an agent's write; `/_/target` holds the same place and reading guards as the other routes; and the target code loses the judgement calls #211 listed. Closes rows 18, 19 and 23 (#211).

**Where (main fac5160):**
- row 18: `mcp.py:336` `_agent_wrote`, called at `:647`, `:657`, `:789`, `:866`; the write is announced earlier in `_write`, `mcp.py:508` (`announce=True`)
- row 19: `hub/handler.py:1666-1679` `_target` goes through `_entry` and `targets.pick`, with no `place.held` and no `_reading` (compare `:1720`, `:1182`, `:1432`)
- row 23: `hub/targets.py:75` `agent_view` and `hub/core.py:636` `member_target` return tuples; the agent target is a bare dict; `targets.choices` imports `tell.who` locally at `hub/targets.py:98` (a cycle); the wire grammar `session | none | agent:<name>` is read in `targets.pick` (`:139-159`), `choices` (`:102`) and `page/page.js:166`

**Blocked by:** None (can start immediately)

**Status:** done-in-PR (sweatshop-ai/sheaf#233)

**Size:** one session if row 23 is taken as two small moves only (the import cycle, the tuples → a small named type); anything more goes in a new ticket and the PR says so

- [x] Test first (18): a tab fetches `/_/doc` the moment after an agent's `reply`; it already shows the new Agent line, and the event the tab got carries it (order: the target is set before `changed` is published, or `_agent_wrote` runs inside the same step)
  - Evidence: `tests/test_hub_target.py::test_the_tabs_hear_of_a_comment_write_after_its_agent_is_the_target[reply|resolve]` and `test_the_tabs_hear_of_an_update_after_its_agent_is_the_target` (red before the fix: the stored target was still the session when `changed` was published; green after): `LiveDocument.comment(before_announce=...)` runs `_agent_wrote` before `_announce`; create and update note the target before `hub.wrote`
- [x] The write still stands when `note_write` raises (`target-failed` row), as today
  - Evidence: `test_a_reply_that_the_target_cannot_follow_still_stands`: `note_write` patched to raise; the reply is in the file, one `changed` was published, one `target-failed` row
- [x] Test first (19): a sheaf closed between the check and the `/_/target` call; the member's own target is not stored and the answer is 404 as for any closed sheaf (9.11)
  - Evidence: `test_the_target_is_judged_and_stored_under_the_sheafs_name` (red without the `_reading` in `_target`): the visibility check and `targets.pick` both run inside `place.held`; `test_a_sheaf_closed_to_the_member_takes_no_target_and_is_a_404`: 404 and `BEA` not in the stored `targets`
- [x] `/_/target` takes the same hold as `/_/cancel` or `/_/comment`; the existing target tests stay green
  - Evidence: `handler.py` `_target` runs `_entry` and `pick` under `self._reading(doc)`, as `_export`; the 53 tests of `test_hub_target.py` and `test_proxy_own_agents.py` stay green
- [x] (23) `targets.choices` no longer imports inside the function: no import cycle between `targets` and `tell`
  - Evidence: `who` moved to `hub/targets.py` (`tell.py` imports it from there, `core.py`'s `from .tell import who` still works); `test_targets_and_tell_import_each_other_nowhere_inside_a_function` (AST: no import in any function of `targets.py`, none from `tell`)
- [x] (23) `member_target` / `agent_view` return a named type or a dataclass; every caller is changed, no behaviour is
  - Evidence: `AgentView` (targets.py) and `MemberTarget` (core.py), frozen dataclasses; callers changed: `tell.py` view, `core.py` `_fresh_meta`, `handler.py` `/_/doc` and `_target`; the existing target, proxy and tell tests unchanged and green
- [x] (23) the three places that know the wire grammar share one parse in Python; `page.js` keeps its own reading and a test names the grammar once for both
  - Evidence: `targets.parse(choice)` and `targets.wire(name)` are the Python reading and writing (`pick`, `choices`); `test_the_wire_grammar_is_read_in_one_place_and_the_page_reads_the_same_words` names the grammar and holds `page.js` `targetNow` to `'none'`, `'session'` and `'agent:'`
