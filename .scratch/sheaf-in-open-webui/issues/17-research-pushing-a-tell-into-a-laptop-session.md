# 17: Research: the ways a server can push a message into a running Claude Code session on a laptop

**Type:** research
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

A page served by the tiroir can name a laptop agent session as its target (tickets 09, 10). Today the laptop hub delivers a Tell into that session locally (SPEC 9.8, 11.3, 11.4); the tiroir has no way in, ticket 10 dropped a laptop-wide relay, and SPEC 9.14's relay serves forked sessions only. Which mechanisms does Claude Code offer, as of November 2026, for something outside the laptop to put a message into a running session: MCP server notifications or elicitations on a connection the session opened itself (the library door over Streamable HTTP), Claude Code channels, Remote Control (the `claude.ai` link of ticket 10), the cross-session messaging the laptop uses (`SendMessage`), hooks that poll, or anything else documented? For each: does it need a resident process or an open inbound port on the laptop, does it reach an idle session or only a turn in progress, what auth it uses, and whether it is documented or only observed. Primary sources: Claude Code docs and changelog, the MCP specification, the local sheaf code (`hub/`, SPEC 9.8 and 9.14).

## Answer

Resolved 2026-11-15 by a research subagent. Findings: branch `research/17-pushing-a-tell` (commit c3a9b92), file `.scratch/sheaf-in-open-webui/research/17-pushing-a-tell-into-a-laptop-session.md`.

- **Best fit: a sheaf mod inside the laptop session.** A `$.clock.every` timer polls the hub with `$.http.fetch` using the door token of ticket 11; on a Tell, `$.prompt.submit` waits until the session is idle and starts a turn. No resident process, no inbound port, no new credential; documented (Claude Code 2.1.311). Limits: a fetch is capped at 30 s (poll in rounds), and after Esc the mod's calls are refused until the user types, so it keeps the Tell and retries.
- **Second fit: cross-machine `SendMessage` over Remote Control.** Nothing new on the laptop, reaches an idle session; but the sender must be a Claude Code session on the tiroir signed in to the member's claude.ai account, and every Tell passes through Anthropic.
- **Works, weaker**: an `asyncRewake` hook long-polling the hub (exit 2 wakes an idle Claude; runs end at their timeout, the Tell arrives as a system reminder). MCP tasks completing on a Tell (public beta; needs a prior tool call; no source describes it as an inbox).
- **Does not fit**: channels (local stdio only, a confirmation at every launch for custom ones, research preview); ordinary MCP server-to-client traffic (2026-07-28 removed the GET stream and unsolicited requests; elicitation asks the user, not Claude); a `ws` MCP server (events' effect undocumented); no documented HTTP API posts into a Remote Control session.
- The mod and the hook are SPEC 9.14's outbound relay poll moved inside the session, so ticket 10's objection (a separate resident process with a token) falls away.
