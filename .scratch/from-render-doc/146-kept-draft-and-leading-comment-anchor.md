# 146: A kept comment draft can go to the wrong paragraph; a leading comment anchor stops a typed task line

**Status:** open

**From:** render-doc ticket 146 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/page/page.js:2802`, `:2809`, `SPEC.md:1242`, `src/sheafmd/edit.py:476-487`, `SPEC.md:478`

**Size:** two items; the second needs a product decision first

- [ ] **A kept new-comment draft can go to the wrong paragraph.** Scene: paragraph P is refused because its ending changed, and another paragraph Q ends with P's old last 12 characters. After the reload, a selection in P gets an empty form and a selection in Q gets P's kept text. Code: `src/sheafmd/page/page.js:2802` (the exclusion on the head match) and `:2809` (the tail fallback). SPEC 10.4 (`SPEC.md:1242`) records it as a known limit. Head, occurrence, tail, block index and quote cannot tell this case from "another paragraph took over P's opening words". Design direction: store a longer lead of the paragraph (about 40 characters) as a new key in the localStorage entry (SPEC 10.8), with the old behaviour for entries without it. Done when a page test of the scene is red on main and green after, and the takeover test `test_a_kept_comment_goes_to_the_paragraph_that_ends_with_its_words_not_to_one_that_took_over_its_opening_words` stays green.

- [ ] **A comment anchor at the very start of a paragraph stops a typed task line from becoming a task item.** `src/sheafmd/edit.py:486-487`: `_typed_tasks` looks only at the paragraph's first child, which is the anchor's token. Repro: block `Buy milk<!--c1-->`, page html `<p><span class="rd-anchor" data-rd-id="c1"></span>- [ ] Buy milk</p>`. It saves as `<!-- sheaf-comment id=c1 ... -->- \[ \] Buy milk`: the words and the comment are kept, and no box is made. Decide, and record it in SPEC 7.2 (`SPEC.md:478`): either state it as a limit, or skip a leading anchor span when looking for the first text, with a test using that html. Low: no text is lost.
