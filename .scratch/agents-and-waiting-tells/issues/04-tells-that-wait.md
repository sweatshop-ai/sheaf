# 04: A Tell to an agent waits on the document

**What to build:** When the target is an agent (ChatGPT, Claude.ai, the Open WebUI assistant), Tell no longer needs a running session: the Tell waits on the document until that agent next calls `documents`, which hands it over with the whole message; the agent acts and replies with role `action`, which ends it (SPEC 9.8, 10.5, 12; D26; design decision 6).

**Blocked by:** 03 (The target is a session or an agent, and the person can change it)

**Claimed by:** Naya 2026-11-07 05:18

**Status:** in-progress

- [ ] Tell (button or comment with `tell`) to an agent target writes the comment and records a waiting Tell in the state folder; it survives a hub restart and has no expiry
- [ ] `documents` with that agent's token lists the document first, even with no other open comment, with `tells` holding the Tell's message; no other token, and no other member's agent, ever sees it
- [ ] The first listing marks it seen (`tell-seen`); listing again changes nothing
- [ ] It ends and is never listed again on that token's `action` reply in the thread (`tell-done`), on a resolve or delete of the thread, on Cancel from the page (`tell-cancelled`), and when the token is revoked
- [ ] A second Tell to the same agent on the same thread while one waits is refused 409 with the SPEC's line; a reply sent with it is still written
- [ ] The page shows "Waiting for <agent>…", then "<agent> has seen it…", with Cancel, across a reload and a restart; no orange dot and no upgrade block for a waiting Tell
- [ ] The door's `instructions` tell the agent to call `documents` first
- [ ] Each step writes its diagnostics row (queued, seen, done, cancelled) with the token's name and never the text
- [ ] Tests: the full loop over the HTTP door with a fake agent token; restart in between; isolation between two tokens; page lines (Playwright)
