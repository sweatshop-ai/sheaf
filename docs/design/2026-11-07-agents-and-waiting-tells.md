# Agents, waiting Tells and the retirement of Ask

**Decided:** 2026-11-07, grilling between Thierry and Claude (session Leire). **Status:** design; SPEC text to follow in this PR, code in the tickets below.

Sheaf should be usable from ChatGPT, Claude.ai and the assistant inside Open WebUI, through MCP, for the members of a proxy-mode hub. Today the MCP door answers on loopback only and takes a fixed token, and a Tell can only be pushed into a running Claude Code session. This page records what was decided and the order of the work.

## Decisions

| # | Decision |
|---|---|
| 1 | Sheaf's tools reach ChatGPT and Claude.ai through the tiroir library door the member already has (OAuth, one door per principal on tiroir-tt), not through a new connector. The door calls the hub on loopback with the agent's token. |
| 2 | First users: Thierry and Hans, on the ThinkingToo hub on tiroir-tt. |
| 3 | First tool set: `documents`, `threads`, `read` (read only), `reply`, `resolve`. `create` and `update` come later. |
| 4 | A new term, **Agent**: one AI client acting for one member. Its replies are signed `Client (Member)`: `ChatGPT (Hans)`, `Claude (Hans)`, and `tiroir (Hans)` for the assistant inside Open WebUI. The signature names the client, never the route: ChatGPT through the tiroir connector is `ChatGPT`. |
| 5 | SPEC 9.7 is rewritten around the agent: one MCP token per agent, the display built by sheaf from client and member, scoped to that member's roots (as member tokens already are in proxy mode). The door picks the token from the MCP `clientInfo`; without one it signs `AI (Member)` and never guesses. |
| 6 | A Tell to an agent that cannot be reached from outside **waits** on the document until the agent next calls `documents`; it then acts and replies with role `action`. No expiry; the person cancels it from the page. |
| 7 | The **target** of a Tell is the last agent session or agent that worked on the document; the page names it and lets the person change it. |
| 8 | **Ask is retired**, everywhere: button, `/_/ask`, `asking` state, adapter `ask`. Logs show it unused (one row in 34,921 on tiroir-tt; two failed rows on the laptop). Replies it left keep role `answer`, which now means "a reply that changed nothing". No migration. |
| 9 | Writes need no confirmation of sheaf's own: ChatGPT already asks before every tool not marked read-only. |
| 10 | The link a tool returns is the page's `/list/...` address on the front, which opens it inside Open WebUI. |

## Order of the work

Each step test-first with its own review.

1. **Retire Ask** in sheaf: SPEC, code, page, adapter.
2. **Agents and waiting Tells:** SPEC 9.7 and 9.8 rewritten, the token per agent, the queue for agents, the target on the page.
3. **The tools in the library door** on tiroir-tt (`thinkingtoo/tiroir-library-mcp`): the five tools, token chosen by `clientInfo`, link to `/list/...`. Tests at three seams: the door call through the hub with the member's agent token, the signature per client, and the refusal of another member's document.
4. **The `tiroir` agent in Open WebUI.**

## SPEC sections the text change touches

9.7 MCP tokens, 9.8 Tell, 9.9 proxy mode (Ask and Tell on the proxy socket), 9.12 (Ask and Tell on James's sessions), 10.5 Ask and Tell on the page, 10.6, 11 the agent adapter (11.2 Ask removed, 11.3 Tell), 11.4 the Claude Code adapter, 12 the MCP door (agents, `documents` listing waiting Tells), 14.5 agent setup, 22. "Ask" appears 96 times in SPEC.md.
