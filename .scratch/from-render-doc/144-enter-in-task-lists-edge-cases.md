# 144: Enter in a task list: nested and ordered lists, an emptied item with a comment, a loose item

**Status:** open

**From:** render-doc ticket 144 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/page/page.js:2946-2980`, `:3010-3013`, `src/sheafmd/edit.py:275`, `tests/page/test_page_writing.py:3682-4012`

**Size:** three exploratory checks; each becomes a page test, and a fix if it fails

The typed-task feature and Enter in a task item are built (SPEC 7.2, `SPEC.md:478`; `_typed_tasks` at `src/sheafmd/edit.py:476`; the Enter handler at `src/sheafmd/page/page.js:2946`; page tests at `tests/page/test_page_writing.py:3682-4012`). None of the three edges below has a test.

- [ ] **Enter in a nested or an ordered task list is not tested.** Try: a `- [ ] a` item with an indented `- [ ] b` under it, and `1. [ ] a`. Press Enter at the end, at the start and on an empty item, type, save, reload. Expect a box on the new item and no raw HTML in the `.md`. Code: `src/sheafmd/page/page.js:2946-2980`. An empty item in a nested list is left to the browser's own outdent (`:2962`), and `start` is removed on the tail list. The only `1. [ ]` test is a unit row (`tests/test_edit_followups.py:586`, a typed numbered line stays text).

- [ ] **A comment anchor in an item made by Enter, then emptied after a save, is not tested.** Try: Enter at the end of a task item, type a word, comment on it, delete the word, wait for the autosave. `_drop_empty_task_items` (`src/sheafmd/edit.py:275`) drops the fresh item that holds the anchor. Check that the comment ends as an orphan cleanly and nothing throws.

- [ ] **Enter with the caret on the `<p>` of a loose task item is not handled.** In `src/sheafmd/page/page.js:3010-3013` the "caret ahead of the box" test covers a caret in the box, the label/item, or inside the label. A caret whose container is the item's wrapping `<p>` (a loose list: `- [ ] a`, blank line, `- [ ] b`; reach it by ArrowUp from the item below or a click in the item's padding) matches none of them, so it falls through to the not-ahead path, which can misplace the caret or the words. The tests at `tests/page/test_page_writing.py:3887-3915` cover only tight lists.
