# 08: Where a Catalog row gets its session

**Type:** research
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 07 put on every Catalog row the session that last changed the page and where it ran (laptop, chat client such as Claude.ai or the Open WebUI assistant, or the tiroir). What does the hub know today about who wrote a file, per write path: a door `create`/`update` (token name, `X-James-Session`), a git root's pull (commit author and message), a save from the page (the member), a file written on disk by a session on the tiroir? For each path: what is recorded, where, and what is missing to name the session and its place. Facts only; read SPEC 9.7, 9.9, 9.12 and the code, change nothing.

## Answer

Full findings: branch `research/08-row-session` (commit 7f7c661), file `.scratch/sheaf-in-open-webui/research/08-where-a-row-gets-its-session.md`. Facts only.

**Short answer: no per-write record in the hub names a session.** A host is written in one place only, the `sessions:` front matter of a sheaf on the list's root, and only by two writes: a member's fork (`machine` from the request body) and James's own-token door write (`host` = `[list].box`) (`hub/handler.py:1432, 1475-1483`). The Catalog's index keeps only the mtime (`index.py:286`); versions are stored by hash with no author; comments are inline in the `.md`, with their `by`.

| Write path | What is recorded about the writer | Where | Missing to name session + place |
|---|---|---|---|
| Door `create`/`update` (and `reply`/`resolve`) | Token name and display `<client> (<member>)` (`state.py:388-395`). `X-James-Session` is read only for a `james_tokens` token (`handler.py:1797-1800`) and becomes a session only for James's own token (`handler.py:1362`) | `door-create`/`door-update` diag rows with token and by (`mcp.py:692-703`; reply and resolve get none, `mcp.py:129`). A commit authored by the display name, only where the root has `commit = true` (`core.py:357-358`). `docs.json` target = last agent token (`targets.py:138-171`) | Chat client: client and member known from the token, no conversation id sent or read. Laptop agent: no session id, no host |
| Library door (tiroir-library-mcp 268934e) | Sends only `Authorization: Bearer` (`sheaf_door.py:256-270`); `clientInfo.name` only picks the token (ChatGPT, Claude, tiroir, else AI) and never reaches the hub (`sheaf_door.py:14-19, 214-217`) | The door's own log has clientInfo (`sheaf_door.py:248-254`) | No `create`/`update` at all (`sheaf_door.py:21-23`); no chat or session id passed |
| Git root pull | Nothing in the hub: a pull writes no row (`commits.py:558-611`), the watcher re-renders it as an outside change (`live.py:598-612`) | Git history only. The hub reads git authorship only through `blame`, for List task boxes (`commits.py:153`, `the_list.py:493`) | A `git log -1 -- file` reader and a commit convention carrying session and host; the hub's own commits carry neither (subject `<what>: <path>`, `commits.py:370`) |
| Save from the page | The member (proxy mode) or the hub's person (loopback) (`core.py:355-358`) | A commit with the member's name and email, only where `commit = true` (`commits.py:363-364`, `proxy.py:428-430`); diag rows only on `save-merged` or a refusal (`handler.py:950-955, 349-357`) | In a non-committing root, nothing but the mtime. The place is the page itself, by construction |
| File written on disk by a session on the tiroir | Nothing; not committed (SPEC 8.11) | Only if the session then runs `sheaf FILE.md`: `docs.json` target {agent, session, pid, name, cwd} plus a `rendered` stamp, no host (`core.py:828-846`, `base.py:43-53`): who last rendered, not who wrote | Any writer identity and any host: the hub records no hostname (`gethostname` only in `seat.py:52`); the diag `session` field is the hub's own (`diagnostics.py:72`) |

**Not checked:** whether the 2026-11-11 library-mcp stage is applied on tiroir-0 (its payload was read on the laptop); the tt-tiroir headersHelper that sets `X-James-Session`; Open WebUI's own logs; any laptop client sending a host.
