# 05: On the proxy socket a member Tells their own agents

**What to build:** A member signed in through the front (Open WebUI) can Tell their own agents from the page, and sees nothing of the hub account's session or of another member's agents (SPEC 9.9). This is what lets Hans send a comment to `ChatGPT (Hans)` from the ThinkingToo hub.

**Blocked by:** 04 (A Tell to an agent waits on the document)

**Claimed by:** Birgit 2026-11-07 07:17

**Status:** done (sheaf#213 merged 2026-11-07 10:06; the boxes below were not re-ticked when it merged, so read the PR for the evidence)

- [ ] On the proxy socket `/_/tell`, `/_/cancel` and `/_/target` serve the member's own agents only; `/_/jump` still answers 404
- [ ] A comment with `tell` goes to the member's own agent, or to James's window or a fork's relay where 9.12 and 9.14 send it, else 400 with the 10.6 line
- [ ] `telling` and the document stream carry only the member's own waiting Tells and drops; nothing of the hub account's session or of another member's agents
- [ ] A member never can pick, see or cancel another member's agent, and never the hub account's session
- [ ] Tests on the proxy socket: two members with an agent each, each sees and controls only their own
