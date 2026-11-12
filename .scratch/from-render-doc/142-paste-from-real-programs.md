# 142: Paste into a paragraph from a real mail client and a real online word processor

**Status:** open (one by-hand check)

**From:** render-doc ticket 142 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `tests/page/test_page_writing.py:1937-1975` (`test_rich_text_pasted_into_a_paragraph_is_saved_as_plain_markdown`, `:1953`)

**Size:** one by-hand session, then two test cases

- [ ] **Pasting from real programs is untested.** The page test at `tests/page/test_page_writing.py:1937-1975` pastes three hand-written `text/html` clipboards (ids `synthetic-*`) shaped like a mail client, a word processor and a web page. Nobody has pasted HTML copied from a real web mail client or a real online word processor into a sheaf paragraph. To do: copy a formatted passage (bold, a link, two paragraphs) from each, paste it into an editable paragraph, save, and check the `.md` holds plain markdown with no `<div>`, `<span>` or `style=`, and the paragraph stays editable. Ideally capture the real clipboard HTML (scrubbed) as two more `PASTED` cases.
