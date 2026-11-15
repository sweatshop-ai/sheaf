# 12: What a laptop session does when the tiroir cannot be reached

**Type:** grilling
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** 11
**Map:** ../map.md

## Question

The laptop is offline, Tailscale is down, or the tiroir itself is down. What does `sheaf FILE.md` and a door write do then: fail and say so, fall back to the laptop hub as today, or keep the write and send it when the tiroir is back (and then how does a queued write meet a page that changed meanwhile, given ticket 05's rule that no agent writes without reading the latest version)? Does the answer differ for a repo page (git already works offline) and a loose page (its original is on the tiroir)?
