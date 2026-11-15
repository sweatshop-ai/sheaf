# 11: How a laptop agent session signs in to the library door, and what `sheaf FILE.md` does then

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 05 made the member's library door the one write path for loose pages, laptop sessions included; ticket 09 has the laptop session declare `X-Sheaf-Session` / `X-Sheaf-Host` on each door write and its `sheaf FILE.md` report the session for repo pages; ticket 10 adds the Remote Control link to that declaration. How does a laptop session sign in to the door: the same OAuth as Claude.ai (one browser sign-in per laptop, a refresh token kept where), or an agent token per member (made where, stored where, revoked how)? And what does `sheaf FILE.md` become: for a loose page, does it call the door's `create`/`update` itself or does the agent call the MCP tools; for a repo page, what does it send the tiroir and does it still start a local hub; what does it print (the tiroir URL, which tiroir, a sign-in hint)?

## Answer

Grilled with Thierry, 2026-11-15 (Ottilie), two rounds, every point as recommended.

- **`sheaf FILE.md` stays the one command.** By default it sends the page to the tiroir when the laptop holds a credential for it; `--local` keeps the laptop hub; no credential, local as today (offline: ticket 12).
- **The credential is an agent token per laptop and member**, made on the tiroir, kept in the login keyring for the CLI and in the MCP headers of Claude Code, revoked by name, as tiroir-0's library door works today. No OAuth from the laptop: the door's OAuth accepts only ChatGPT and Claude connector callbacks.
- **It signs as the agent kind**: a new client `Claude Code`, signed `Claude Code (Thierry)`; a Codex session gets `Codex`. The Catalog row also shows the session's name (ticket 09), which the write declares in `X-Sheaf-Session` / `X-Sheaf-Host` with its Remote Control link (ticket 10).
- **A loose page**: the CLI calls the door's `create` the first time and `update` after, with the hash it last read. It keeps, in its state folder, local path → tiroir, address, last hash. A refused `update` writes the tiroir's text beside the file as `FILE.tiroir.md`, records it as read, and exits non-zero telling the agent to merge and run again; `sheaf pull FILE.md` fetches the latest before an edit. Neither the agent's text nor the person's is overwritten. The Catalog folder is `--folder <name>`, else the month (`2026-11`).
- **A repo page**: the CLI uploads no text, git carries it. It sends the tiroir a render report (repo, path, commit, session, machine, Remote Control link), never pushes, and warns when the commit is not on the remote yet.
- **What it prints**: the tiroir's https URL; then which tiroir, as whom and as which agent (`on tiroir-tt as Thierry · Claude Code`); then the push warning (repo page) or the folder (loose page).
- Follows from the above, for the spec: the door's `clientInfo` table gains Claude Code and Codex, and the CLI sends the client of the adapter it detected; the laptop's install step makes the token on the tiroir and stores it once on the laptop (keyring and MCP entry).

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

Round 2 (all four as recommended): signature `Claude Code (Thierry)` / `Codex (Thierry)` with the session's name on the row; a refused loose-page update leaves `FILE.tiroir.md` beside the file and `sheaf pull FILE.md` reads the latest; `--folder`, else the month; the printed lines as in the answer.
