# 08: Where a Catalog row gets its session

**Type:** research
**Status:** open
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 07 put on every Catalog row the session that last changed the page and where it ran (laptop, chat client such as Claude.ai or the Open WebUI assistant, or the tiroir). What does the hub know today about who wrote a file, per write path: a door `create`/`update` (token name, `X-James-Session`), a git root's pull (commit author and message), a save from the page (the member), a file written on disk by a session on the tiroir? For each path: what is recorded, where, and what is missing to name the session and its place. Facts only; read SPEC 9.7, 9.9, 9.12 and the code, change nothing.
