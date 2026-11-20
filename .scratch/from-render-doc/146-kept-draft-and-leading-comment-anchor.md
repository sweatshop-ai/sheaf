# 146: A kept comment draft can go to the wrong paragraph; a leading comment anchor stops a typed task line

**Claimed by:** Naya 2026-11-20 20:05

**Status:** done (#510 merged as 967da586)

**Blocked by:** 144 (same code, edit.py and page.js, task-line Enter)

**From:** render-doc ticket 146 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/page/page.js:2802`, `:2809`, `SPEC.md:1242`, `src/sheafmd/edit.py:476-487`, `SPEC.md:478`

**Size:** two items; the second needs a product decision first

- [x] **A kept new-comment draft can go to the wrong paragraph.** Scene: paragraph P is refused because its ending changed, and another paragraph Q ends with P's old last 12 characters. After the reload, a selection in P gets an empty form and a selection in Q gets P's kept text. Code: `src/sheafmd/page/page.js:2802` (the exclusion on the head match) and `:2809` (the tail fallback). SPEC 10.4 (`SPEC.md:1242`) records it as a known limit. Head, occurrence, tail, block index and quote cannot tell this case from "another paragraph took over P's opening words". Design direction: store a longer lead of the paragraph (about 40 characters) as a new key in the localStorage entry (SPEC 10.8), with the old behaviour for entries without it. Done when a page test of the scene is red on main and green after, and the takeover test `test_a_kept_comment_goes_to_the_paragraph_that_ends_with_its_words_not_to_one_that_took_over_its_opening_words` stays green.

- [x] **A comment anchor at the very start of a paragraph stops a typed task line from becoming a task item.** `src/sheafmd/edit.py:486-487`: `_typed_tasks` looks only at the paragraph's first child, which is the anchor's token. Repro: block `Buy milk<!--c1-->`, page html `<p><span class="rd-anchor" data-rd-id="c1"></span>- [ ] Buy milk</p>`. It saves as `<!-- sheaf-comment id=c1 ... -->- \[ \] Buy milk`: the words and the comment are kept, and no box is made. Decide, and record it in SPEC 7.2 (`SPEC.md:478`): either state it as a limit, or skip a leading anchor span when looking for the first text, with a test using that html. Low: no text is lost.

**Done 2026-11-20 (#510, merged as 967da586, head 3cb4fed3; review round 1 GO, exit 0):**
- Kept draft: the entry now carries `lead` (the paragraph's first 40 characters). `tests/page/test_page_writing.py::test_a_kept_comment_goes_to_the_paragraph_whose_opening_it_has_not_to_another_that_ends_like_it_did` failed on main (the paragraph that ends like the refused one got the comment) and passed after; all 30 `kept_comment` page tests passed on t-compute, the takeover test among them. Entries without `lead` behave as before. SPEC 10.4 and 10.8 updated.
- Leading anchor: decided to skip leading comment tokens in `_typed_tasks` (`src/sheafmd/edit.py`), not to state a limit. `tests/test_edit_followups.py` gained two tests (the line becomes a task item and keeps its comment; a box with no words keeps its characters); that file and `tests/test_edit_markers.py` passed locally, 343 tests. SPEC 7.2 updated.
- Not done: `_lines_as_items` (a task item whose first text is an anchor) still does not skip a leading anchor; the ticket did not ask for it.
