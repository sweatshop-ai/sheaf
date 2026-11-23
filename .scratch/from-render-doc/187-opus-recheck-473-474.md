# 187: Opus re-check of the merged PRs #473 and #474

**Claimed by:** Lior

**Status:** done (2026-11-23, PR #637, merged as 73dd4130; follow-up PR #642, merged as 505b328e)

**Blocked by:** none

**From:** a correctness review of two PRs merged without a Codex round: #473 (merge a746a2a4) and #474 (merge a30694be, ticket 160). Codex was at its usage limit until 2026-11-24T12:39Z, so the review ran as the Opus fallback of `/codex-review`, one fresh agent per PR. Both were triaged against main 55da34fa. Letters continue from 183 and 185 (last used: BY): BZ and CA.

**Counts:** 2 findings:

- 0 serious.
- 2 minor, both still present on main.
- Already filed or fixed on main: see the last section.

Ratings follow the rule of 183. Serious means a wrong result in ordinary use, a crash, data loss, or a security or privacy breach. Minor means the defect needs narrow input, a narrow race or an unusual setup, or it only changes a status code, a log row or the form of the source.

**Verdict:** GO on both PRs. #473's own change is correct. Main replaced it in c4fddbd1, and BZ is a regression in that replacement, not in #473.

**Where:** `src/sheafmd/edit.py` (BZ), `src/sheafmd/page/live.js` (CA).

Each item has one box. Write a red test on main first for each. If an item cannot be reproduced, leave its box unticked and give the reason.

## Serious

None.

## Minor

- [x] **BZ** (from #473, regression in c4fddbd1): `strip_data_attrs` edits quoted attribute values.
  - **Where:** `edit.py:530` (`_DATA_ATTR_RE`), used by `strip_data_attrs` (`edit.py:533`) and called from `_comparable`.
  - **Cause:** `_DATA_ATTR_RE` runs over the whole start tag. It also matches whitespace followed by `data-` inside another attribute's quoted value, and `[^\s=>/]+` swallows the closing quote.
  - **Effect:** the source side of the comparison becomes broken HTML. `_sanitize` keeps the page fragment's value intact, so the two never compare equal.
  - **Verified on main:** `strip_data_attrs('<a href="https://x.y" title="the data-sheet">spec</a>')` returns `<a href="https://x.y" title="the>spec</a>`.
  - **Reproduction:** take this markdown:

    ```
    # M

    - [ ] Deploy a/b#1: [spec](https://x.y "the data-sheet")
    - [ ] Merge a/b#2: two
    ```

    - From the row: `the_list.tick_edit(text, 1, "Merge")` returns `None`, so the row's button refuses the tick.
    - From the page: `_toggle_boxes` returns `None`, so the save falls back to pandoc and rewrites the whole list (bullet style, a capital `X`).
    - Any later save: `_unchanged` stays False for this block.
    - Same list with the title "the sheet": the tick works.
    - #473's narrower regex ticked this input.
    - Any rendered attribute value holding whitespace then `data-` (for example raw `<abbr title="… data-driven">`) hits the same path.
  - **Fix direction:** strip whole attributes only. One way is to tokenise the tag's attributes (name, optional `=` value with quoted values matched as a unit) and drop those named `data-*` but not `data-rd-*`. The other is to parse with BeautifulSoup and delete the attributes the way `_sanitize` does. Pin it with the link-title case.
  Done in PR #637 (2026-11-23): `strip_data_attrs` reads each start tag's attributes one by one (`_ATTR_RE`, a quoted value taken whole) and drops the ones named `data-`, `data-rd-` too, as `_sanitize` does (`edit.py:75-78`); a name straight after a quote or a `/` counts, as html.parser reads it. Red on main: `tests/test_edit_data_attr_values.py` (`test_a_row_ticks_when_a_link_title_holds_data` with "the data-sheet"; "the sheet" is the control). Merged as 73dd4130.

- [x] **CA** (from #474): after a 409 the leader reconnects with the same shared stream id, so every tab of the browser can go without live updates for up to 300 s.
  - **Where:**
    - `live.js:181-197`: `Leader.prototype.connect` always opens `/_/live?shared=` + `this.sid`, and its `onerror` with `readyState === 2` clears `joined` and `es` but keeps `sid`.
    - `live.js:258`: `take`, on a join while `!this.es`, calls `connect()` with that same `sid`.
    - `hub/handler.py:1027-1029`: the hub refuses an id held by another owner with 409.
    - The new id is drawn only on the reopen path (`live.js:249`), not here.
  - **Scenario:** proxy mode, with a member switch and a stale connection at the same time:
    - Member A's shared stream S is still registered on the hub, because a half-open downstream hid the drop.
    - The browser's cookie is now member B's.
    - The EventSource reconnects to `?shared=S` as B and gets 409 (readyState 2). The leader tells the tabs `down` with s=2.
    - Each tab joins again 2 s later. `take` calls `connect()` with S, which gets 409 again.
    - This repeats every 2 s until the hub drops A's stale stream (`proxy.STREAM_SECONDS`, 300 s).
    - It heals by itself and loses no text.
  - **Red test:** a `tests/page/test_page_shared_live.py`-style test whose route answers `/_/live?shared=<first id>` with 409 every time. Assert that the next `/_/live?shared=` request carries a different id and that a document stream opens.
  - **Fix direction:** when the leader's EventSource is refused (readyState 2), set `this.sid = rnd()` before the next `connect()`.
  Done in PR #637 (2026-11-23): on a refused connection (readyState 2) the leader draws a new `sid` and clears a pending RETRY reopen (`again`, `deferred`), which belonged to the connection that just ended. Page test `test_a_shared_stream_refused_409_is_opened_again_under_a_new_id` in `tests/page/test_page_shared_live.py`: red in CI (run 45242478345, attempt 2) before the fix, green after (run 45258544706). Merged as 73dd4130.

- [x] **Follow-up from #637's review (minor; Opus fallback round 1 on f1164b71):** a start tag holding an unpaired quote keeps its `data-` attributes on the source side.
  - **Where:** `edit.py:528` (`_START_TAG_RE`), used by `strip_data_attrs`.
  - **Cause:** `_START_TAG_RE` reads a `'` or `"` as the opening of a quoted value, so a bare value holding a quote (`href=a'b`) leaves the tag unmatched and nothing in it is stripped. html.parser reads `a'b` as one bare value and `_sanitize` strips the tag's `data-` attributes, so the two sides differ and that block's boxes refuse the tick.
  - **Reproduction:** `strip_data_attrs('<a href=a\'b data-x="1" title="t">x</a>')` returns the input unchanged; `BeautifulSoup(that, "html.parser").a.attrs` is `{'href': "a'b", 'data-x': '1', 'title': 't'}`. `_START_TAG_RE.search(that)` is `None`.
  - **Not a regression of #637:** main before #637 left the same tag unchanged too (the start-tag pattern did not change). The review's claim that the old regex stripped it does not hold.
  - **Fix direction:** let `_START_TAG_RE` (and `_ATTR_RE`'s bare value) take a quote inside a bare value, as html.parser's `attrfind_tolerant` does (`(?!['"])[^>\s]*`), with a test on this input.
  - **Correction on where it occurs:** not in a list row. Pandoc escapes an inline tag holding an unpaired quote (`<a href=a'b …>` in a row is text, `&lt;a`), so no row's boxes refuse the tick. Pandoc passes a raw HTML block through as written (`<div class=a'b data-x=1>blk</div>`): on main that block's `_unchanged` was False, so every save sent it through pandoc.
  Done in PR #642 (2026-11-23): `_START_TAG_RE` reads the tag attribute by attribute, as html.parser's `locatestarttagend_tolerant` does: a quote opens a quoted value only straight after a name's `=`, so names and bare values may hold one, and an `=` inside a bare value (`<a href=a="x>y">`) opens nothing; the tag ends at its first `>`. `_ATTR_RE` takes the same names and bare values. The loops are possessive (a looser first version was exponential on a tag that never closes, 2.1 s at 22 quoted values). Red on main: `tests/test_edit_data_attr_values.py` (stripped output, parity with BeautifulSoup's attributes, `_unchanged` on a raw HTML block with a browser-serialised fragment, a linear-time guard). Review: boss_review round 1 provisional GO by the Opus fallback on a663d1fe, its two minors fixed in 11b72450, fix pass round 2 GO with no findings; CI green. Merged as 505b328e.

## Already filed or fixed on main

Checked on #474 and not counted as findings:

- 171 items 1-5: the poll in `Shared.get`, the member `accept`, a refused join reopening the stream (#539), the `pageshow` rejoin (#539), and events lost in a leader hand-over (#542, #589).
- 169: a frozen leader relays nothing.
- 170: a crashed tab is counted until the sweep.
- 180 and 183 AC: a join overtook the tab's own lock.
- 181 D: a stale `/live/join` after a hand-over.
- 185 BD: `Subscription.put` read `on_put` twice (#624).

Checked and clean on #474:

- Events reach the right tab.
- Owner checks hold on join and leave.
- `doc` in the request body goes through `_unalias`, `is_clients` and `_entry`, with no traversal or cross-document leak.
- Lock order is consistent.
- Every subscription closes on close, replace, leave, a late join and a join to a closed stream.
- Hub stop is drained in order.
- Pages fall back to one stream each without Web Locks or BroadcastChannel.
- The asset hash includes `live.js`.
