# 11: How a laptop agent session signs in to the library door, and what `sheaf FILE.md` does then

**Type:** grilling
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 05 made the member's library door the one write path for loose pages, laptop sessions included; ticket 09 has the laptop session declare `X-Sheaf-Session` / `X-Sheaf-Host` on each door write and its `sheaf FILE.md` report the session for repo pages; ticket 10 adds the Remote Control link to that declaration. How does a laptop session sign in to the door: the same OAuth as Claude.ai (one browser sign-in per laptop, a refresh token kept where), or an agent token per member (made where, stored where, revoked how)? And what does `sheaf FILE.md` become: for a loose page, does it call the door's `create`/`update` itself or does the agent call the MCP tools; for a repo page, what does it send the tiroir and does it still start a local hub; what does it print (the tiroir URL, which tiroir, a sign-in hint)?

## Working notes (grilling, Ottilie with Thierry, 2026-11-15)

Facts gathered before round 1:
- The laptop reaches tiroir-0's library door today with a static bearer per principal over Tailscale (`~/.claude.json` `tiroir-library`, `http://100.121.96.109:8772/mcp`, `Authorization` header; tiroir-library-mcp `library_mcp/tokens.py`, hashes only, scope `principal:<id>`).
- The door's OAuth accepts only ChatGPT and Claude connector callbacks (`library_mcp/door_consent.py:86`, read at 87dba59 in the `yusuf-codex` checkout): a loopback redirect from a laptop CLI is refused.
- The door picks the hub token from `clientInfo.name`, falling back to the member's `AI` token (SPEC 9.7): a laptop Claude Code session would sign `AI (Thierry)` today.

Round 1 (all four as recommended):
- A loose page is written by `sheaf FILE.md`: the CLI calls the door's `create` the first time, `update` after, with the hash it last read; a page changed meanwhile refuses the write. Agents keep the one command they know.
- The laptop's credential is an agent token per laptop and member, made on the tiroir, kept in the login keyring for the CLI and in the MCP headers for Claude Code, revoked by name, as tiroir-0's door works today. No OAuth from the laptop.
- A repo page: `sheaf FILE.md` uploads no text (git carries it); it sends the tiroir a render report (repo, path, commit, session, machine, Remote Control link), never pushes, prints the URL and warns when the commit is not on the remote yet.
- `sheaf FILE.md` goes to the tiroir by default when the laptop holds a credential for it; `--local` keeps the laptop hub; no credential, local as today. Offline is ticket 12.
