# 03: The target is a session or an agent, and the person can change it

**What to build:** A document's target is the last agent session or agent that worked on it (SPEC 9.8, design decision 7). The page names it and lets the person pick another from what they may Tell. A Tell still reaches only a session in this ticket; an agent target shows as chosen, with Tell to it arriving in 04.

**Blocked by:** 01 (Retire Ask end to end), 02 (Agent tokens signed `Client (Member)`)

**Claimed by:** Mikkel 2026-11-07 03:32

**Status:** in-progress

- [ ] A door write (`reply`, `resolve`, `create`, `update`) with an agent's token makes that agent the target; `documents`, `threads` and `read` change nothing
- [ ] A render from a session still makes the session the target; the session is kept beside an agent target so the person can take it back
- [ ] In proxy mode each member has their own target per document, only ever one of their own agents; the hub's person's target can be a session or any agent
- [ ] `POST /_/target {doc, target}` takes `session`, `agent:<token name>` or `none`, answers `{target, targets}`, and refuses 400 a target the reader may not pick
- [ ] `/_/doc` and the meta block carry `target`, `targets` and the agent shape of 10.1; the page's Agent line offers **Change** when `targets` holds another
- [ ] A revoked token is no target: the page shows the 10.6 line for it
- [ ] Tests: door write vs read; target per member; `/_/target` refusals; the page's Change list (Playwright)
