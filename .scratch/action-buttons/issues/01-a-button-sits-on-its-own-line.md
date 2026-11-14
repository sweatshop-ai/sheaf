# 01: A one-off action is a button on its own line

**What to build:** on a page, a task line of a one-off action word is drawn as a red button where its line is, inside the text, with the rest of the line as its text beside it; no longer in the row above the document. The list (9.10) keeps its row. Undo for 5 s, the press, the lock and "who pressed it" stay as SPEC 10.11 says. A page with several buttons of the same word (fourteen `Merge` lines) shows each on its own line, so which one was pressed is never ambiguous.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [x] Two `- [ ] Approve` lines on one page are two buttons, each pressing its own box — `test_two_lines_of_the_same_word_are_two_buttons_and_each_presses_its_own_box` (tests/page/test_page_actions.py), green in CI on the PR head
- [x] Selecting words on a button's line still opens the chat box, and does not press — `test_a_selection_on_a_buttons_line_does_not_press_it_and_the_button_is_not_part_of_the_text`, green in CI; a press no longer closes an open comment form (`.rd-inline` in the popover's mousedown exclusion)
- [x] The row above the document is gone on pages that are not the list's sheaves — `test_a_page_with_no_toggle_has_no_row_above_the_document`, green in CI (the row stays only for Share until ticket 03, and for a one-off whose box the page does not find)
- [x] SPEC 10.11 and GLOSSARY say where the button is drawn — SPEC.md 10.11 first paragraph, GLOSSARY.md One-off action
