# 164: The list reads a task line inside a fenced code block in a list item as an action

**Status:** open

**From:** render-doc ticket 164 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/the_list.py:325-343` (`read_sheaf`), `:404-412` (`_boxes`), `:418` (`tick_edit`); `SPEC.md:1003`

**Size:** one session; red test first in `tests/test_hub_list.py`

- [ ] **A false action chip, and the real action next to it cannot be ticked.** `read_sheaf` (`src/sheafmd/hub/the_list.py:325-343`) takes every `- [ ] <word>` line of a `list` block from `split_md_blocks`, and a fence (or indented code, or an HTML comment) inside a list item stays part of that list block. Result: a false action chip whose tick is refused (409), and the real action in the same list cannot be ticked from the list either, because `tick_edit` (`the_list.py:418`) finds the block's marks differ from the boxes the renderer draws. `_boxes` (`the_list.py:404-412`) has the same flaw. `SPEC.md:1003` already says a line in a code block or HTML block is no action, so the code disagrees with the spec.
  - Reproduce: `read_sheaf("a.md", "# T\n\n- item\n  ```\n  - [ ] Approve\n  ```\n- [ ] Done\n")` lists two actions (`Approve` on line 4, `Done` on line 6), and `tick_edit(..., 0, "Approve")` and `tick_edit(..., 1, "Done")` both return `None`.
  - Fix: keep a list block's actions only when its marks match the boxes the render draws (the check `ticked_html` makes), or re-split each item's dedented body and skip code and HTML blocks.
