# 18: How a Tell pressed on a page on the tiroir reaches the laptop session that is its target

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** 17
**Map:** ../map.md

## Question

When a member presses Tell on a page served by the tiroir and the page's target is an agent session running on their laptop, how does the Tell get there? Candidates, to be judged on the research of the ways a server can push into a running session: the session hears it on its next call to the library door (as a waiting Tell for an agent does, SPEC 9.8), a push over the door connection the session already holds, the per-fork relay of SPEC 9.14 generalised to every laptop session that rendered a page, or the Tell going instead to the member's own agent on the tiroir. What does the page show while it waits (queued, seen, done), what happens when the session has ended or the laptop is off (ticket 12), and does the laptop hub still deliver locally for a page it serves itself?

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (one round, all eight recommendations accepted), on the research of ticket 17 (branch `research/17-pushing-a-tell`).

1. **A sheaf mod inside the laptop's Claude Code session delivers the Tell.** It polls the tiroir and hands the Tell over with `$.prompt.submit`, which waits until the session is idle and starts a turn. No Remote Control `SendMessage` (it needs a signed-in Claude session on the tiroir and puts Anthropic in the path).
2. **The mod loads in every session with the sheaf plugin and stays quiet** until that session has sent a page to the tiroir (`sheaf FILE.md`, or a door `create`/`update`); only then does it poll.
3. **A 25-second long-poll**, under the mods' 30-second limit per call: the door answers as soon as a Tell arrives. On the tiroir a Tell to a session waits in the queue as a Tell to an agent does (9.8), keyed by the session id.
4. **A session's Tells go only to the door token of the member who declared that session** (tickets 09, 11). The declared id is unverified, so another member's token that claims the same id gets nothing.
5. **The page shows 9.8's states**: queued until the mod takes it, seen when it has, done when the session replies in the thread with role `action`. Claude reads the message with sheaf named as sender, not as the member typing.
6. **No expiry.** With the session ended or the laptop off, the Tell waits on the page ("waiting for <session>"); the member cancels it or retargets it to their own agent. A session resumed with the same id (`claude --resume`) picks it up. After an Esc the mod keeps the Tell and delivers it on the member's next input.
7. **The laptop hub is unchanged**: for a page it serves itself it still delivers locally (11.3).
8. **`sheaf relay` retires when the mod lands**: forks get their Tells through the same mod, so 9.14's separate process and relay token go.
