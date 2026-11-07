# 02: Agent tokens signed `Client (Member)`

**What to build:** The hub's person can make a token for one AI client acting for one member, and every reply that token writes is signed `<client> (<member>)`, built by sheaf, never typed (SPEC 9.7, D27; design decisions 4 and 5). `ChatGPT (Hans)` for Hans's ChatGPT token, `AI (Hans)` for the token a door uses when it does not know the client.

**Blocked by:** None (can start immediately)

**Claimed by:** Mikkel 2026-11-07 01:42

**Status:** in-progress

- [ ] `sheaf token add <name> --client <client> [--write]` makes an agent's token; `--client` and `--as` together are refused; the client is cleaned by the display-name rule, at most 40 characters, without parentheses
- [ ] The row stores `client` and no `display`; `add` prints the name it will sign with; `list` shows the client and that name
- [ ] A door reply with an agent's token is signed `<client> (<member name>)`, the member being the one whose `tokens` name the token; in loopback mode or with no member, the hub's person's name
- [ ] Renaming the member in the config changes the signature after a restart
- [ ] `add` refuses a client whose built name equals a member's name or another token's display
- [ ] Tokens made before (with `display`, no `client`) sign exactly as before and are never agents
- [ ] Tests over the HTTP door: the signature per client, `AI (<member>)`, and an old token unchanged
