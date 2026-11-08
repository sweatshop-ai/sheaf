# 07: The `tiroir` agent in Open WebUI

**What to build:** The assistant inside Open WebUI on the ThinkingToo front works on sheaf pages for the signed-in member, signs `tiroir (<member>)`, and picks up the Tells that wait for it (design decision 4, step 4 of the design's order).

**Blocked by:** 06 (Sheaf's tools in the tiroir library door)

**Claimed by:** Thierry 2026-11-08 (box steps)

**Status:** in-progress (built as the tt-tiroir stage hermes-sheaf-2026-11-07, PR 745, merged; it waits on apply on tiroir-tt, which Thierry does; the boxes below stay open until then)

- [ ] The Open WebUI assistant reaches the library door as the signed-in member and its calls use that member's `tiroir` token
- [ ] Its replies on a page read `tiroir (Hans)` for Hans, never `ChatGPT` or `AI`
- [ ] A Tell Hans sends to `tiroir (Hans)` from a page is listed to the assistant at its next `documents`, acted on, and answered with role `action`; the page's waiting line ends
- [ ] Another member's assistant never sees Hans's documents or Tells
