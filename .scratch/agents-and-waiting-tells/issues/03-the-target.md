# 03: The target is a session or an agent, and the person can change it

**What to build:** A document's target is the last agent session or agent that worked on it (SPEC 9.8, design decision 7). The page names it and lets the person pick another from what they may Tell. A Tell still reaches only a session in this ticket; an agent target shows as chosen, with Tell to it arriving in 04.

**Blocked by:** 01 (Retire Ask end to end), 02 (Agent tokens signed `Client (Member)`)

**Claimed by:** Hugo 2026-11-07 03:32

**Status:** done

- [x] A door write (`reply`, `resolve`, `create`, `update`) with an agent's token makes that agent the target; `documents`, `threads` and `read` change nothing (tests/test_hub_target.py: door write vs read, refused write)
- [x] A render from a session still makes the session the target; the session is kept beside an agent target so the person can take it back (render sets `kind: session`, `session` kept beside an agent target, `pick("session")` takes it back)
- [x] In proxy mode each member has their own target per document, only ever one of their own agents; the hub's person's target can be a session or any agent (test_a_members_agent_write..., test_each_member_has_their_own_target..., test_a_member_cannot_pick_another_members_agent_nor_the_hub_accounts_session: 400)
- [x] `POST /_/target {doc, target}` takes `session`, `agent:<token name>` or `none`, answers `{target, targets}`, and refuses 400 a target the reader may not pick (`targets.pick`, 400 on `Refused`; answers `{target, targets}`)
- [x] `/_/doc` and the meta block carry `target`, `targets` and the agent shape of 10.1; the page's Agent line offers **Change** when `targets` holds another (`/_/doc`, meta block, page Change list: tests/page/test_page_target.py)
- [x] A revoked token is no target: the page shows the 10.6 line for it (shape carries `revoked: true`; the 10.6 REVOKED line; same-name new token is not the old target, keyed on the token id)
- [x] Tests: door write vs read; target per member; `/_/target` refusals; the page's Change list (Playwright) (tests/test_hub_target.py 39, tests/page/test_page_target.py 3 Playwright; CI run 42335430759 green on 480182a, PR #211, review rounds 1-3 GO as the Opus fallback)
