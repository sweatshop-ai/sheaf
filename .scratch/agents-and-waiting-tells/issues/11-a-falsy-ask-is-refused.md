# 11: A comment body with any `ask` is refused, with one message

**What to build:** `ask` in a comment body of `add` or `reply` is refused 400 "Ask was retired: use Tell, or reply." whatever its value (`false`, `0`, `""`, `null` included), and the retired-Ask line exists once. Closes rows 11 and 14 (#210).

**Where (main fac5160):** `hub/handler.py:1524` `_comment` tests `b.get("ask")` (truthiness); the message is `ASK_RETIRED` at `hub/handler.py:77` and again in words at `deliver.py:142`.

**Blocked by:** None (can start immediately)

**Status:** done-in-PR

**Size:** small, well under one session

- [x] Test first: `ask` set to `false`, `0`, `""`, `null` and `true` on add and on reply each answer 400 with the retired line and write nothing (evidence: tests/test_hub_handler.py::test_a_comment_with_any_ask_value_is_refused_and_writes_nothing, 10 cases; red before the fix for false, 0, "", null on both ops)
- [x] A body with no `ask` key is accepted as today (evidence: the existing add/reply tests in tests/test_hub_handler.py, tests/test_hub_work.py pass unchanged: 529 passed across the 5 touched files)
- [x] Decide in the PR whether `null` counts as sent (key present) and say so in the test name (evidence: case id `null_counts_as_sent`; handler.py `"ask" in b`)
- [x] `deliver.py:142` and `handler.py:77` share one message (one constant, imported); the text of both answers is unchanged (evidence: tests/test_hub_handler.py::test_the_retired_ask_line_exists_once; test_agents_envelope.py and the old handler tests still match the old text))
