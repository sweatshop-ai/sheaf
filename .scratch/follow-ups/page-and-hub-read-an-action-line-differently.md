# The page and the hub read an action line differently

**What to build:** the page's `ACTION_LINE` (page.js) judges a box's line from rendered, whitespace-collapsed `textContent`; the hub's `_ACTION_RE` (the_list.py) judges raw markdown. They disagree on lines such as `- [ ] Merge <!-- note -->` or `- [ ] Merge ![](x)` (hub: action; page: bare `Merge`, no action) and `- [ ] **Merge** a/b#1` (hub: no action; page: action). The page's check only decides whether a tick waits for a reload while the file's buttons are unknown (`mayBeAction`, SPEC 10.11), so the cost is a box ticked as a plain one, or held for a reload. The difference holds for every older word too (`**Approve**`); Codex review 1 of PR #275 (run by Karim) found it, not caused by that PR.

**Blocked by:** None.

**Status:** done

- [x] Decide which reading is right: the hub's raw markdown. The page cannot ask the hub when it needs the answer (it does not know the file's buttons then) and holds only rendered HTML, so its check is made a superset of the hub's: a rendered line that begins with one of the words and a space or its end, whatever follows
- [x] A test with each of the three lines above, and with a plain line that only begins with the letters of a word (`tests/page/test_page_action_line.py`, #507, f8abb42a: red on the old `page.js`, 5 failed; green after, CI run 44790768975)

## Resolution

The page's `ACTION_LINE` no longer checks the argument of a word, so `Merge <!-- note -->` and `Merge ![](x)` (rendered `Merge`) are held like any action. The false positive `**Merge** a/b#1` (hub: no action) is accepted: it waits for a reload, which costs less than a hub action ticked as a plain box. A plain word that only begins with the letters of an action (`Mergers are hard`) is still a plain box. SPEC 10.11 says so. The superset also holds an ordinary task that begins with an action word (`Done reading`) for a reload while the page does not know the buttons: accepted, it costs a reload and never a wrong tick.
