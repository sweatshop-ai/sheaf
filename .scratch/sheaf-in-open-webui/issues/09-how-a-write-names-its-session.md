# 09: How a write names its session and place

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 07 puts on every Catalog row the session that last changed the page and where it ran; ticket 08 found that no write path records that today. For each path (the library door's `create`/`update` from Claude.ai, ChatGPT or the Open WebUI assistant; a laptop agent through the door; a git root's pull; a save from the page; a file written on disk by a session on the tiroir), what does the row show, and how does the hub learn it: a session and host argument on the door, a commit trailer for git roots, a per-write journal in the hub, or a coarser row (client and member only) where the session cannot be known? Decide what the spec requires and what the row shows when it is missing.

## Answer

Grilled with Thierry, 2026-11-15 (Ottilie). Research: branch `research/09-conversation-ids` (commit 6865566), file `.scratch/sheaf-in-open-webui/research/09-conversation-ids.md`.

**What a row shows.** The last write (who and from where) and, beside it, the last agent session, which is a link: "Hans · page, before Dimitri". A human save never hides the way back to the session. The place is a class (laptop, chat client, tiroir, page), the machine name in a tooltip only when the writer declared it.

| Write path | The row | The click |
|---|---|---|
| Laptop session, door write | session name · laptop | back to the session, as `/_/jump` does today |
| Laptop session, repo page arriving by git pull | the session its laptop `sheaf FILE.md` reported to the tiroir, made precise by `Sheaf-Session:` / `Sheaf-Host:` commit trailers where present; neither: "git · <author>" | when the session is known |
| Open WebUI assistant | Open WebUI (member) | opens `<origin>/c/<chat_id>`, the chat id sent on the door's connection only (a `{{CHAT_ID}}` header, never the global user-info switch); only the chat's own user can open it |
| Claude.ai, ChatGPT | Claude.ai (member) | none: Claude.ai sends no conversation id, ChatGPT's `openai/session` forms no URL and is not kept |
| File written on disk by a session on the tiroir | the session of its next `sheaf FILE.md`, host the tiroir; none: "tiroir · ?" | when the session is known |
| Save from the page | member · page | none on the member; the agent session beside it keeps its click |

**How the hub learns it.** The hub keeps a **Write log**: one line per write, every path (loose pages and non-committing roots have no git; a pull feeds it too). A laptop session declares its id and machine on each door write in headers, `X-Sheaf-Session` and `X-Sheaf-Host` (generalising `X-James-Session`), set by the headersHelper from the local registry; the hub records them as declared, unverified, since they never open a transcript. Known limit: a headersHelper runs at connect, so after `/clear` it sends the old id until the MCP reconnects. A render (`sheaf FILE.md`) counts as the session's declaration that it wrote the page; render and write are not the same act, so a session that edits without rendering again leaves the row on the session before.

**The click.** The spec requires that the session's name brings Thierry back to it on the laptop it runs on, as today. How the click reaches that laptop (the page calling the local AgentView from the browser, or a laptop-wide relay carrying a jump) is ticket 10's prototype. From another device, or for another member, the name shows who and where only.

## Working notes (grilling, Ottilie with Thierry, 2026-11-15)

Round 1:
- The session cell is a **link to the session**, not a label only (Thierry chose the link over the recommended label).
- A save from the page counts as the last write: the row shows the member and "page".
- The hub keeps its own record of writes, one line per write, for every path (loose pages and non-committing roots have no git); a git pull feeds the same record.
- The place shows as a class (laptop, chat client, tiroir, page), the machine name in a tooltip only when the writer declares it.

Research for round 2 (conversation ids reaching the door): branch `research/09-conversation-ids`. Only Open WebUI can send a chat id that forms a link (`/c/<chat_id>`, opt-in: `ENABLE_FORWARD_USER_INFO_HEADERS` or a per-connection `{{CHAT_ID}}` header). ChatGPT sends `_meta["openai/session"]`, an anonymized conversation id: it groups writes, it forms no URL. Claude.ai sends no conversation id (documented). The MCP spec has no conversation field; `Mcp-Session-Id` is gone in 2026-07-28. A Claude Code `headersHelper` gets no session id of its own; the `X-James-Session` route reads the local registry.

Round 2 was put to Thierry and he asked to clarify before answering (2026-11-15).

Clarification (Thierry): "today I click the agent's name (Dimitri) on a page and get back to the session; does that disappear on Open WebUI?" What it is today: the byline name is a button, `POST /_/jump {doc}` (SPEC 8.5, 10.1 item 11), which runs the local `[jump]` command (on Thierry's laptop a curl to AgentView `127.0.0.1:8765/api/jump`, `[reopen]` for an ended session); it answers 404 on the proxy socket, and the hub never connects to a laptop (9.14). So Q5 is reframed: the click is kept, and the question is how it reaches the laptop the session runs on.

Round 2:
- The click on the session's name brings Thierry back to that session on the laptop, as `/_/jump` does today. The spec requires the click; the way it reaches the laptop (the page calling the local AgentView from the browser, or a laptop-wide relay carrying a jump) is chosen by a prototype that tries both (to be opened as its own ticket).
- A laptop session declares its id and machine on every door write in headers (`X-Sheaf-Session`, `X-Sheaf-Host`, generalising `X-James-Session`), set by the headersHelper from the local registry, and the hub records them as declared, unverified: they never open a transcript. Known limit (research 09): a headersHelper runs at connect, so after `/clear` it sends the old id until the MCP reconnects.

Round 3 explained to Thierry with pros and cons (Open WebUI chat id per connection vs global switch vs label; Claude.ai/ChatGPT label only, keep `openai/session` or not; git pages: render report vs commit trailers vs author only, noting ticket 05 makes git the main path for laptop repo pages; tiroir disk writes: render vs door only). New question raised: a human save after an agent's write hides the session link (round 1 Q2), so does the row also keep the last agent session?

Round 3:
- Open WebUI assistant: the chat id is sent on the door's connection only (a custom header with `{{CHAT_ID}}`), never by the global user-info switch; the name opens `<origin>/c/<chat_id>`, which only the chat's own user can open. A per-tiroir install step.
- Claude.ai and ChatGPT: a label only (`Claude.ai (Thierry)`), no click; ChatGPT's `openai/session` is not kept.
- A file written on disk by a session on the tiroir takes its session from its next `sheaf FILE.md` (the tiroir's machine as host); without one the row shows "tiroir · ?" with no click.
- Repo pages arriving by git: the session comes from the laptop's `sheaf FILE.md` reporting to the tiroir; `Sheaf-Session:` / `Sheaf-Host:` commit trailers add precision where present; neither, the row shows "git · <author>" with no click.
- The row keeps the last agent session beside the last write ("Hans · page, before Dimitri"), so a human save never hides the way back.
