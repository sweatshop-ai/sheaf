# 15: Small tidy-ups in the comment route, the Tell docstring, the box waits and the CSS names

**What to build:** Four readability fixes with no change in behaviour. Closes rows 12, 13, 15 and 16 (#210).

**Where (main fac5160):**
- row 12: `hub/tell.py:328-329` docstring "as for an a Tell begun by hand"
- row 13: `hub/handler.py:1540`, `:1548`, `:1550`, `:1568`, `:1597`, `:1603-1606`: the `to_box = True` flag, replaced by `route == "box"` (and `route` set where `to_box` is)
- row 15: `hub/boxwait.py:42` `Drop.kind` and `:59` `BoxWaits.add(doc, thread, kind, ...)`; the drop file keeps `kind: "tell"`
- row 16: `page/page.css:52,72` and `page/page.js:1731`: `rd-st-ask`, `rd-who-ask`

**Blocked by:** 09 (Waiting Tells: per-owner seen, the route re-checked, a recycled thread id)

**Status:** ready-for-agent

**Size:** small, one session; 09 edits the same lines of `_comment`, hence the block

- [ ] Test first, where there is one: the comment route's existing tests for box, relay, agent and session stay green without edit; `BoxWaits.add` loses `kind` and its callers and tests change in the same commit
- [ ] The old drop files with `kind: "tell"` still read after a restart (one test)
- [ ] Row 16 is decided, not guessed: keep the class names (and say the asset cache needs no bump), or rename them and bump the asset version; the PR records which and why
- [ ] The docstring reads as English
