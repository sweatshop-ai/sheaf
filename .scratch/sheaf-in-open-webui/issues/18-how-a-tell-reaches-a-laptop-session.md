# 18: How a Tell pressed on a page on the tiroir reaches the laptop session that is its target

**Type:** grilling
**Status:** open
**Blocked by:** 17
**Map:** ../map.md

## Question

When a member presses Tell on a page served by the tiroir and the page's target is an agent session running on their laptop, how does the Tell get there? Candidates, to be judged on the research of the ways a server can push into a running session: the session hears it on its next call to the library door (as a waiting Tell for an agent does, SPEC 9.8), a push over the door connection the session already holds, the per-fork relay of SPEC 9.14 generalised to every laptop session that rendered a page, or the Tell going instead to the member's own agent on the tiroir. What does the page show while it waits (queued, seen, done), what happens when the session has ended or the laptop is off (ticket 12), and does the laptop hub still deliver locally for a page it serves itself?
