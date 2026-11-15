# 09: How a write names its session and place

**Type:** grilling
**Status:** open
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 07 puts on every Catalog row the session that last changed the page and where it ran; ticket 08 found that no write path records that today. For each path (the library door's `create`/`update` from Claude.ai, ChatGPT or the Open WebUI assistant; a laptop agent through the door; a git root's pull; a save from the page; a file written on disk by a session on the tiroir), what does the row show, and how does the hub learn it: a session and host argument on the door, a commit trailer for git roots, a per-write journal in the hub, or a coarser row (client and member only) where the session cannot be known? Decide what the spec requires and what the row shows when it is missing.
