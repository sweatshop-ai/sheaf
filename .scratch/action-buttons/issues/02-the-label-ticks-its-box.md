# 02: A tick box's label ticks it

**What to build:** on a plain task line, the label (the words before the first `:` or ` — `, else the first word) is clickable and ticks or unticks the box, like a `<label>`. The rest of the line is ordinary text: a click there does nothing, a selection opens the chat box, a link opens. Example: in `- [ ] Approved: the quote of 12 November`, "Approved" ticks the box.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] A click on the label ticks; a second click unticks (a plain box, not an action)
- [ ] A click on the rest of the line does not tick
- [ ] A drag-selection that starts on the label opens the chat box and does not tick
- [ ] Works on a phone (touch target at least 44 px high, as the action buttons)
