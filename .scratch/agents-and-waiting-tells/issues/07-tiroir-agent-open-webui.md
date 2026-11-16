# 07: The `tiroir` agent in Open WebUI

**What to build:** The assistant inside Open WebUI on the Acme front works on sheaf pages for the signed-in member, signs `tiroir (<member>)`, and picks up the Tells that wait for it (design decision 4, step 4 of the design's order).

**Blocked by:** 06 (Sheaf's tools in the tiroir library door)

**Claimed by:** Alice 2026-11-08 (box steps)

**Status:** in-progress (built as the agency-tiroir stage hermes-sheaf-2026-11-07, PR 745, merged; it waits on apply on agency-tiroir, which Alice does; the boxes below stay open until then)

- [ ] The Open WebUI assistant reaches the library door as the signed-in member and its calls use that member's `tiroir` token
- [ ] Its replies on a page read `tiroir (Bob)` for Bob, never `ChatGPT` or `AI`
- [ ] A Tell Bob sends to `tiroir (Bob)` from a page is listed to the assistant at its next `documents`, acted on, and answered with role `action`; the page's waiting line ends
- [ ] Another member's assistant never sees Bob's documents or Tells
