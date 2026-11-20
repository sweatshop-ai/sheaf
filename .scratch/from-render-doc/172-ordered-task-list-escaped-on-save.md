# 172: An ordered list whose items start with `[ ]` is saved with the brackets escaped

**Status:** ready-for-agent

**Blocked by:** none

**From:** found by Mira while testing ticket 144 (PR #476), 2026-11-20

**Where (main 3a999b92):** `src/sheafmd/render.py:806` (`pandoc_html`), `src/sheafmd/edit.py` (`html_block_to_md`, `_typed_tasks`, `_boxes_as_text`), `SPEC.md` 7.2

**Size:** one decision (box or text), then a writer fix and a test

An ordered list item written `1. [ ] one` is not a task item here. The page shows the characters `[ ] one` as words and Enter in it is the browser's own. A save of that block then writes the brackets escaped, so the file changes meaning for anyone who reads it on GitHub, which draws a box for `1. [ ]`.

## Evidence

`pandoc_html("1. [ ] one\n2. [x] two\n")` returns:

```
<ol type="1">
<li>[ ] one</li>
<li>[x] two</li>
</ol>
```

No checkbox. The round trip of that block as the page would send it back (`pandoc -f gfm -t html5`, then `rde.html_block_to_md(html, block.content)`) gives `1.  \[ \] one` and `2.  \[x\] two`, where the source was `1. [ ] one` and `2. [x] two`. The same holds for `3. [ ] starts at three`. A bullet list (`- [ ] outer` with a nested `- [x]`) and a loose bullet list round-trip unchanged. A save of another block leaves all of them byte for byte.

## To do

- [ ] Decide what an ordered `[ ]` item is: a task item with a box (as GitHub draws it), or words. Either way, an edit of the block must not change the file's text.
- [ ] A test: an ordered list `1. [ ] one` edited elsewhere in the same block is written back with `[ ]` as it was.
- [ ] If it becomes a task item: Enter in it makes a numbered item with an unticked box (ticket 144's handler and tests for bullet lists are the model; it is the same `TASK_BOX` path in `src/sheafmd/page/page.js`).
