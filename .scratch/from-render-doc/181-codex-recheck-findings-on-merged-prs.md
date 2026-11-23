# 181: Codex findings on merged PRs, still open on main

**Claimed by:** Kenji 2026-11-23 (clusters A and B)

**Status:** open

**Blocked by:** none

**From:** the re-check of Codex NO-GO findings on merged PRs, triaged against main e5af8068 on 2026-11-23 (the last review round of each PR). Already fixed and not repeated here: #475 (three findings), #480, #483 (three findings); #498 is not a bug; the #489 DELETE race is ticket 99 line 26.

**Where:** `src/sheafmd/hub/place.py` `place`; `src/sheafmd/mcp.py` `_created`, `_write`, `_update`; `src/sheafmd/edit.py` `_styled_marks`, `_unwrap_strays`, the emoji preservation; `src/sheafmd/hub/core.py` lifecycle token; `src/sheafmd/hub/handler.py` lifecycle DELETE and `/live/join`; `src/sheafmd/hub/the_list.py` `_MAY_HOLD_CODE_RE`.

One box per item. Red test first on main for each; an item that cannot be reproduced stays unticked with the reason.

## A. A commit's root id comes from the root captured (serious, from #495)

- [ ] `place.py:742` `place`: `rid = hub.root_id_of(address)` reads the root by name after `_where` captured it. A root forgotten and its name taken by another folder between the two commits the move into the other repo. Use `root.id`.
- [ ] `mcp.py:1171` `_created`: the same, between `_new_address` and the read of the id. Use `root.id`.
- [ ] `mcp.py:669` (`_write`) and `mcp.py:1266` (`_update`): check whether they have the same flaw.

## B. Pasted styled spans (from #481)

- [ ] Serious: a nested `font-weight:400` or `font-style:normal` is ignored. `<span style="font-weight:700">bold <span style="font-weight:400">plain</span></span>` saves `**bold plain**` (`edit.py:211-219`). The inner span must end the mark.
- [ ] Minor: the style regex matches a substring. `--font-weight:bold` saves `**plain**` (`edit.py:213-214`). Parse the style as declarations.

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
