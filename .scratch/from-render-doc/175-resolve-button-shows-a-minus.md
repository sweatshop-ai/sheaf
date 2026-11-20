# 175: The Resolve button in the comment box is drawn as a minus sign


**Claimed by:** Zeynep 2026-11-20 18:32

**Status:** done

**Blocked by:** none

**From:** asked by the owner, 2026-11-20

**Where (main bb3eafb8):** `src/sheafmd/page/page.js:2164-2174` (`bandHtml`), `src/sheafmd/page/page.css:130` (`#rd-popover .rd-head button`), `tests/page/test_page_chat_box.py:107`, `SPEC.md:1262`, `SPEC.md:1269`, `SPEC.md:1302`

**Size:** small: one glyph, its tests and three SPEC lines

The band of the comment box (the popover a comment opens in) has a Resolve button, `data-a="status"` with title and aria-label "Resolve", drawn as `−` (−). Beside the Close button (×) it reads as "minimize". The owner wants a small check mark instead, the same weight and size as the ×, not a large emoji such as ✅.

## To do

- [x] Draw Resolve as a check mark: U+2713 or a thin inline SVG, whichever renders the same in the browsers CI runs. It matches the × in weight, size and opacity. The title and aria-label stay "Resolve". Evidence: PR 500 merged as becb429b; page.js `bandHtml` draws `CHECK` (inline SVG, 14x14, stroke 1.7); `test_the_check_resolves_an_open_thread_and_stays_while_writing` passed (83 passed in test_page_chat_box.py and test_page_mobile_refocus.py on t-compute, then 73 after review fixes; CI run 44784809111 success, Chromium on t-compute plus CI's browsers).
- [x] Check every other place that draws the resolve glyph or names the minus sign: the comments at `page.js:2164`, `page.js:2434` and `page.js:3336`, `tests/page/test_page_mobile_refocus.py:3`, and the menu entry at `page.js:3025`. Evidence: the same test asserts `svg.rd-check` is the only content and the aria-label is "Resolve"; title unchanged.
- [x] Update `SPEC.md` where it names the minus sign (the box description, the action table and the touch paragraph). Evidence: no U+2212 left in src/, SPEC.md or README.md (grep by the review agent); the menu entry at page.js:3025 is the word "Resolve" and needed no change; comments at 2164, 2434 and 3336 and the refocus docstring updated.
- [x] A test: the button titled "Resolve" in an open thread's band shows the check, not U+2212, and still resolves the thread (`tests/page/test_page_chat_box.py:107` asserts the minus today and is the one to change). Page tests run in CI or on t-compute only. Evidence: SPEC.md box paragraph, action table and touch paragraph updated in becb429b.
