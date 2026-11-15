# 17: Research: the ways a server can push a message into a running Claude Code session on a laptop

**Type:** research
**Status:** open
**Blocked by:** none
**Map:** ../map.md

## Question

A page served by the tiroir can name a laptop agent session as its target (tickets 09, 10). Today the laptop hub delivers a Tell into that session locally (SPEC 9.8, 11.3, 11.4); the tiroir has no way in, ticket 10 dropped a laptop-wide relay, and SPEC 9.14's relay serves forked sessions only. Which mechanisms does Claude Code offer, as of November 2026, for something outside the laptop to put a message into a running session: MCP server notifications or elicitations on a connection the session opened itself (the library door over Streamable HTTP), Claude Code channels, Remote Control (the `claude.ai` link of ticket 10), the cross-session messaging the laptop uses (`SendMessage`), hooks that poll, or anything else documented? For each: does it need a resident process or an open inbound port on the laptop, does it reach an idle session or only a turn in progress, what auth it uses, and whether it is documented or only observed. Primary sources: Claude Code docs and changelog, the MCP specification, the local sheaf code (`hub/`, SPEC 9.8 and 9.14).
