# 142: Paste into a paragraph from a real mail client and a real online word processor

**Claimed by:** Habib 2026-11-20 16:21

**Status:** merged as 48a49fa0 (PR 481; the two open items below remain). PR: https://github.com/sweatshop-ai/sheaf/pull/481 (head eb4eea0c, review GO recorded by boss_review.py, exit 0; CI 5 of 6 slices green, slice 1 red only on `test_mount_sheaf.py::test_connect_a_laptop_names_it_and_shows_one_line_once`, which also fails on main, run 44769354075)

**Blocked by:** none (the owner runs the paste live with a guiding worker, 2026-11-20)

**From:** render-doc ticket 142 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `tests/page/test_page_writing.py:1937-1975` (`test_rich_text_pasted_into_a_paragraph_is_saved_as_plain_markdown`, `:1953`)

**Size:** one by-hand session, then two test cases

- [x] **Live paste from a real web mail client and a real online word processor, 2026-11-20.** Evidence: web mail pasted clean (the `.md` held `**bold**`, `*italic*`, `[google](https://www.google.com/)`, two paragraphs and a nested list; no `<div>`, `<span>` or `style=`; blocks stayed `contenteditable`). The online word processor paste found two bugs: bold lost, and a paragraph holding a lone `\` from its empty line. Both reproduced through `edit.html_block_to_md`, red tests written, fixed in `_unwrap_strays` (PR 481); the DOM Chrome builds from that clipboard was read back from `outerHTML` and is a unit test. 285 passed in `tests/test_edit_followups.py`.
- [ ] **Capture the real word-processor clipboard HTML (scrubbed).** The web-mail clipboard is a scrubbed capture (`captured-web-mail`); the word-processor case is `reconstructed-online-word-processor`, built from a description, never recorded. The in-tab capture listener died on every save (the paragraph saves on blur and the save reloads the page). Next time arm the listener in `page.js` of the hub under test from the start (it survives the reload), paste once, read `localStorage`.
- [ ] **Two `<br>` in a row inside one `<p>` still write backslash lines** (real shape unknown, no capture).
- [x] (original item) **Pasting from real programs is untested.** The page test at `tests/page/test_page_writing.py:1937-1975` pastes three hand-written `text/html` clipboards (ids `synthetic-*`) shaped like a mail client, a word processor and a web page. Nobody has pasted HTML copied from a real web mail client or a real online word processor into a sheaf paragraph. To do: copy a formatted passage (bold, a link, two paragraphs) from each, paste it into an editable paragraph, save, and check the `.md` holds plain markdown with no `<div>`, `<span>` or `style=`, and the paragraph stays editable. Ideally capture the real clipboard HTML (scrubbed) as two more `PASTED` cases.
