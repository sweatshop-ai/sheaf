# 144: Enter in a task list: nested and ordered lists, an emptied item with a comment, a loose item

**Claimed by:** Mira 2026-11-20 16:00

**Status:** done, PR #476 merged as 3142ee6b (2026-11-20)

**Blocked by:** none

**From:** render-doc ticket 144 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/page/page.js:2946-2980`, `:3010-3013`, `src/sheafmd/edit.py:275`, `tests/page/test_page_writing.py:3682-4012`

**Size:** three exploratory checks; each becomes a page test, and a fix if it fails

The typed-task feature and Enter in a task item are built (SPEC 7.2, `SPEC.md:478`; `_typed_tasks` at `src/sheafmd/edit.py:476`; the Enter handler at `src/sheafmd/page/page.js:2946`; page tests at `tests/page/test_page_writing.py:3682-4012`). None of the three edges below has a test.

- [x] **Enter in a nested or an ordered task list is not tested.** Try: a `- [ ] a` item with an indented `- [ ] b` under it, and `1. [ ] a`. Press Enter at the end, at the start and on an empty item, type, save, reload. Expect a box on the new item and no raw HTML in the `.md`. Code: `src/sheafmd/page/page.js:2946-2980`. An empty item in a nested list is left to the browser's own outdent (`:2962`), and `start` is removed on the tail list. The only `1. [ ]` test is a unit row (`tests/test_edit_followups.py:586`, a typed numbered line stays text).

- [x] **A comment anchor in an item made by Enter, then emptied after a save, is not tested.** Try: Enter at the end of a task item, type a word, comment on it, delete the word, wait for the autosave. `_drop_empty_task_items` (`src/sheafmd/edit.py:275`) drops the fresh item that holds the anchor. Check that the comment ends as an orphan cleanly and nothing throws.

- [x] **Enter with the caret on the `<p>` of a loose task item is not handled.** In `src/sheafmd/page/page.js:3010-3013` the "caret ahead of the box" test covers a caret in the box, the label/item, or inside the label. A caret whose container is the item's wrapping `<p>` (a loose list: `- [ ] a`, blank line, `- [ ] b`; reach it by ArrowUp from the item below or a click in the item's padding) matches none of them, so it falls through to the not-ahead path, which can misplace the caret or the words. The tests at `tests/page/test_page_writing.py:3887-3915` cover only tight lists.

## Outcome (2026-11-20, PR #476, merged as 3142ee6b)

Evidence: CI run 44781359409 on head 8120f493, slices 2 to 6 green. Slice 1 was red only on `tests/page/test_mount_sheaf.py::test_connect_a_laptop_names_it_and_shows_one_line_once`, the flake that #497 fixed on main. Review: one recorded Codex round, GO.

1. Nested and ordered: page tests for nested (end, start, empty), an outer item with a sublist, and ordered. In pandoc gfm `1. [ ] x` is plain text, so an ordered item gets no box and Enter there is the browser's; this is documented by a test and followed up in ticket 172. An empty nested item is left to the browser's outdent and is asserted loosely (no raw HTML, the words kept). Seven server tests show a save of another block writes task lists back byte for byte.
2. Comment anchor: a test comments on an Enter-made item, deletes the word and checks that no box is left, the comment survives and parses, and nothing throws. The orphan outcome described above was not observed: once Edit mode is left the item is no longer `data-rd-fresh`, so `_drop_empty_task_items` does not drop it.
3. Loose item: fixed in `src/sheafmd/page/page.js`. A caret on the `<li>` or on the `<p>` that wraps a loose item's label is moved to the start or the end of the words first. Two page tests (offset 0 and end).

Not covered: a caret on a nested `<ul>` between inner items puts the new item after the outer item. This is unchanged by the PR and untested.
