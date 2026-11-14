# The page and the hub read an action line differently

**What to build:** the page's `ACTION_LINE` (page.js) judges a box's line from rendered, whitespace-collapsed `textContent`; the hub's `_ACTION_RE` (the_list.py) judges raw markdown. They disagree on lines such as `- [ ] Merge <!-- note -->` or `- [ ] Merge ![](x)` (hub: action; page: bare `Merge`, no action) and `- [ ] **Merge** a/b#1` (hub: no action; page: action). The page's check only decides whether a tick waits for a reload while the file's buttons are unknown (`mayBeAction`, SPEC 10.11), so the cost is a box ticked as a plain one, or held for a reload. The difference holds for every older word too (`**Approve**`); Codex review 1 of PR #275 (run by Karim) found it, not caused by that PR.

**Blocked by:** None.

**Status:** open

- [ ] Decide which reading is right (the hub's raw markdown, probably) and make the page ask the hub's reading (the answer's actions) instead of its own regex, or make the two agree
- [ ] A test with each of the three lines above
