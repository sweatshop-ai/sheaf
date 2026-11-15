# 11: How a laptop agent session signs in to the library door, and what `sheaf FILE.md` does then

**Type:** grilling
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 05 made the member's library door the one write path for loose pages, laptop sessions included; ticket 09 has the laptop session declare `X-Sheaf-Session` / `X-Sheaf-Host` on each door write and its `sheaf FILE.md` report the session for repo pages; ticket 10 adds the Remote Control link to that declaration. How does a laptop session sign in to the door: the same OAuth as Claude.ai (one browser sign-in per laptop, a refresh token kept where), or an agent token per member (made where, stored where, revoked how)? And what does `sheaf FILE.md` become: for a loose page, does it call the door's `create`/`update` itself or does the agent call the MCP tools; for a repo page, what does it send the tiroir and does it still start a local hub; what does it print (the tiroir URL, which tiroir, a sign-in hint)?
