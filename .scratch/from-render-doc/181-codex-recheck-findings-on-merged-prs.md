# 181: Codex findings on merged PRs, still open on main

**Claimed by:** Kenji 2026-11-23 (clusters A and B)

**Status:** A and B in a PR on branch `kenji/181-captured-root`; C to F open

**Blocked by:** none

**From:** the re-check of Codex NO-GO findings on merged PRs, triaged against main e5af8068 on 2026-11-23 (the last review round of each PR). Already fixed and not repeated here: #475 (three findings), #480, #483 (three findings); #498 is not a bug; the #489 DELETE race is ticket 99 line 26.

**Where:** `src/sheafmd/hub/place.py` `place`; `src/sheafmd/mcp.py` `_created`, `_write`, `_update`; `src/sheafmd/edit.py` `_styled_marks`, `_unwrap_strays`, the emoji preservation; `src/sheafmd/hub/core.py` lifecycle token; `src/sheafmd/hub/handler.py` lifecycle DELETE and `/live/join`; `src/sheafmd/hub/the_list.py` `_MAY_HOLD_CODE_RE`.

One box per item. Red test first on main for each; an item that cannot be reproduced stays unticked with the reason.

## A. A commit's root id comes from the root captured (serious, from #495)

- [x] `place.py:742` `place`: `rid = hub.root_id_of(address)` reads the root by name after `_where` captured it. A root forgotten and its name taken by another folder between the two commits the move into the other repo. Use `root.id`. Red first: `tests/test_hub_place.py::test_a_move_never_commits_into_a_root_that_took_the_name_of_the_one_it_moved_in` (on main the move was committed in the other repo).
- [x] `mcp.py:1171` `_created`: the same, between `_new_address` and the read of the id. Use `root.id`. Red first: `tests/test_hub_commits.py::test_a_create_never_commits_into_a_root_that_took_the_name_of_the_one_it_wrote_in`.
- [x] `mcp.py:669` (`_write`) and `mcp.py:1266` (`_update`): check whether they have the same flaw. Checked, no change: neither holds a root before it reads the id, and both read it before the write resolves its root by name. A swap before the read names the new root for both; a swap after it leaves the id of the old one, and `committed` refuses.

## B. Pasted styled spans (from #481)

- [x] Serious: a nested `font-weight:400` or `font-style:normal` is ignored. `<span style="font-weight:700">bold <span style="font-weight:400">plain</span></span>` saves `**bold plain**` (`edit.py:211-219`). The inner span must end the mark. Done: a span that says a normal weight or style ends a mark the paste made from a styled span; an authored `<b>` and a heading stay as they were (the existing test "a span in a mark" keeps `<b><span style="font-weight: 400">` bold). Red first: `tests/test_edit_followups.py::test_a_pasted_span_that_says_normal_ends_the_mark_of_the_span_around_it`.
- [x] Minor: the style regex matches a substring. `--font-weight:bold` saves `**plain**` (`edit.py:213-214`). Parse the style as declarations. Done, also for the `<b style="font-weight:normal">` check. Red first: `test_a_style_that_only_holds_the_words_of_a_bold_or_italic_declaration_stays_plain`, `test_a_bold_declaration_among_others_or_marked_important_is_bold`, `test_a_b_whose_style_only_holds_the_words_of_a_normal_weight_stays_bold`.

## C. Lifecycle restart token (from #489, minor)

- [ ] The token counter restarts at 0 in every hub process (`core.py:200`, `:1897`, `:1908`): a late `DELETE ?token=1` of run A clears run B's announcement.
- [ ] `'²'.isdigit()` is true, so `int()` raises `ValueError` and the request is a 500 (`handler.py:2706`). Use `fullmatch` on `[0-9]+`.

## D. Stale `/live/join` after a leader hand-over (from #484, minor)

- [ ] `handler.py:1021-1036` calls `leave(key)` on a newer stream when an old join arrives late. Either the handler ignores it, or `Leader.stop` (`live.js:168`) aborts the request with an `AbortController`. Needs a page test with a delayed old join.

## E. Emoji token provenance (from #479, minor)

- [ ] `edit.py:979-994`: the check is a substring check over the whole block, so an authored span is rewritten when `:+1:` appears only inside code.
- [ ] A U+F8FE or U+F8FF character in the block turns the preservation off.

## F. `the_list` code detection (from #477, minor)

- [ ] `the_list.py:358` `_MAY_HOLD_CODE_RE` misses an ordered item that opens with markup, `1. <div>`.
