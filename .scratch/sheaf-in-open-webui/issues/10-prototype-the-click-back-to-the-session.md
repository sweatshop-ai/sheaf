# 10: How the click on a session's name gets back to the laptop

**Type:** prototype
**Status:** open
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 09 requires that the session's name on a page or Catalog row served by the tiroir brings Thierry back to that session on his laptop, as `POST /_/jump` (SPEC 8.5, 4.3 `[jump]`/`[reopen]`) does today, where the hub runs a local command to AgentView (`127.0.0.1:8765/api/jump`). On the tiroir the hub never connects to a laptop (9.14) and `/_/jump` answers 404 on the proxy socket. Which way works, tried for real: (a) the page, open in the laptop's browser, calls the local AgentView directly (Chrome's rules for an https page reaching `127.0.0.1`, AgentView's `X-Fleet` check and CORS); (b) a relay the laptop keeps open to the tiroir, laptop-wide rather than per fork (9.14 today), that carries a jump and runs the same `[jump]` command. A throwaway prototype of each, linked from this ticket, for Thierry to try; also what the name does on a device where neither works.
