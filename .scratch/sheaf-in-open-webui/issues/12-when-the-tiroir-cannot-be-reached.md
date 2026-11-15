# 12: What a laptop session does when the tiroir cannot be reached

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** 11
**Map:** ../map.md

## Question

The laptop is offline, Tailscale is down, or the tiroir itself is down. What does `sheaf FILE.md` and a door write do then: fail and say so, fall back to the laptop hub as today, or keep the write and send it when the tiroir is back (and then how does a queued write meet a page that changed meanwhile, given ticket 05's rule that no agent writes without reading the latest version)? Does the answer differ for a repo page (git already works offline) and a loose page (its original is on the tiroir)?

## Answer

Grilled with Thierry, 2026-11-15 (Ottilie), one round, every point as recommended.

- **A loose page falls back to the laptop hub, with no queue.** When the tiroir cannot be reached, `sheaf FILE.md` renders on the laptop hub as today and says so loudly: the local URL, then `not on tiroir-tt: run sheaf FILE.md again when it is back`. Nothing runs in the background. Running it again later is the only send: `create` if the page never reached the tiroir, else `update` with the hash last read; a page changed meanwhile is refused and leaves `FILE.tiroir.md` to merge (ticket 11). Ticket 05's rule holds with no new mechanism. The same holds for an existing loose page edited offline: `sheaf pull` fails, the agent edits the copy it last read, and the later `update` carries that hash.
- **A repo page falls back the same way, and its render report is dropped.** Git carries the text offline anyway; only the render report (session, machine, Remote Control link) does not leave. It is not queued: the Catalog row gets its session from the next render that reaches the tiroir, or from commit trailers (ticket 09).
- **Only an unreachable tiroir falls back.** A connection timeout (about 5 s, Tailscale down, the tiroir down) or a 5xx from the tiroir opens the laptop hub. A refused credential (401/403: token revoked or expired) fails loudly with no fallback, because a silent fallback would hide a problem that needs fixing.
- Follows for the spec: an agent calling the door's MCP tools directly while offline gets the tool's error; there is nothing to fall back to.
