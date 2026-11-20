# 175: The Resolve button in the comment box is drawn as a minus sign


**Claimed by:** Zeynep 2026-11-20 18:32

**Status:** in-progress

**Blocked by:** none

**From:** asked by the owner, 2026-11-20

**Where (main bb3eafb8):** `src/sheafmd/page/page.js:2164-2174` (`bandHtml`), `src/sheafmd/page/page.css:130` (`#rd-popover .rd-head button`), `tests/page/test_page_chat_box.py:107`, `SPEC.md:1262`, `SPEC.md:1269`, `SPEC.md:1302`

**Size:** small: one glyph, its tests and three SPEC lines

The band of the comment box (the popover a comment opens in) has a Resolve button, `data-a="status"` with title and aria-label "Resolve", drawn as `−` (−). Beside the Close button (×) it reads as "minimize". The owner wants a small check mark instead, the same weight and size as the ×, not a large emoji such as ✅.

## To do

- [ ] Draw Resolve as a check mark: U+2713 or a thin inline SVG, whichever renders the same in the browsers CI runs. It matches the × in weight, size and opacity. The title and aria-label stay "Resolve".
- [ ] Check every other place that draws the resolve glyph or names the minus sign: the comments at `page.js:2164`, `page.js:2434` and `page.js:3336`, `tests/page/test_page_mobile_refocus.py:3`, and the menu entry at `page.js:3025`.
- [ ] Update `SPEC.md` where it names the minus sign (the box description, the action table and the touch paragraph).
- [ ] A test: the button titled "Resolve" in an open thread's band shows the check, not U+2212, and still resolves the thread (`tests/page/test_page_chat_box.py:107` asserts the minus today and is the one to change). Page tests run in CI or on t-compute only.
