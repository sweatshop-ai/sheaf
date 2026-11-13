# 04: Merge, Deploy and Install are action words

**What to build:** `Merge`, `Deploy` and `Install` join the fixed list of one-off action words (9.10). Their argument is the rest of the line (`Merge sweatshop-ai/sheaf#272: …`), which the hub does not read; AgentView's merge desk does. The list stays fixed: no author can make a new word.

**Blocked by:** None (can start immediately).

**Status:** ready-for-agent

- [ ] `- [ ] Merge owner/repo#N: text` is a one-off action; pressing it writes `[x]` and nothing else
- [ ] A save that unticks a pressed Merge is refused as for the other one-offs, but a write by another process (AgentView unticking a refused merge) is taken as an outside change
- [ ] SPEC 9.10's table lists the three words
