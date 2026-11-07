# 06: Sheaf's tools in the tiroir library door

**What to build:** Thierry and Hans use sheaf from ChatGPT and Claude.ai through the tiroir library door they already have on tiroir-tt (OAuth, one door per member), with no new connector (design decisions 1, 2, 3, 9, 10). Work in `thinkingtoo/tiroir-library-mcp`, not in sheaf.

**Blocked by:** 02 (Agent tokens signed `Client (Member)`), 04 (A Tell to an agent waits on the document)

**Status:** ready-for-agent

- [ ] The door offers `documents`, `threads`, `read` (read-only, marked so), `reply` and `resolve`; not `create` or `update`
- [ ] It calls the hub on loopback with the token of the agent that called, chosen from the caller's MCP `clientInfo`; an unknown client or none uses the member's `AI` token; the client names each app really sends are recorded from observed `initialize` calls
- [ ] Links in results are the page's `/list/...` address on the front, which opens it inside Open WebUI
- [ ] Waiting Tells reach the agent through `documents`
- [ ] Tests at three seams: a door call through the hub with the member's agent token; the signature per client; another member's document is refused as not existing
- [ ] One agent token per client per member is made on tiroir-tt and named in that member's `tokens`, for Thierry and Hans
