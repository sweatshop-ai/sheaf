# 03: Share becomes a tick box

**What to build:** Share (9.11), today a blue toggle button in the row above the document, becomes a tick box with its label, `- [ ] Shared with the team`; only the owner may tick or untick it, as today. Existing files keep working: `- [ ] Share` is read as before.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] The owner ticks and unticks it by its label; another member's tick is refused as today
- [ ] `- [ ] Share` and `- [ ] Shared with the team` both work; the list keeps its button
- [ ] The tiroir-tt routines that read the box still find it (check `thinkingtoo/tt-tiroir` before merging)
