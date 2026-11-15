# 21: Moving a single page to another tiroir, and how its old address forwards there

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 04 decided that a root moved to another tiroir behaves like Google Drive: pages move with their versions and comments, and the old address leads to the new one. It left the mechanics and the single page open. Can one page move to another tiroir (a loose page Thierry made on tiroir-tt that belongs to Marina on tiroir-0), and what happens when that goes against its root's tiroir (a repo page whose `.sheaf.toml` names tiroir-tt)? How does the old address forward across tiroirs: a redirect kept by the first tiroir's hub, for how long, and what a member who cannot sign in to the second tiroir sees? Do comments, versions and the Write log (ticket 09) go along, and who may make the move? Builds on the forwarding of a moved page within one tiroir.

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (two rounds; Q5 reworded at his request to tell the user what to do).

Fact found first: client tiroirs already exist (`tiroir-avetta-o`, `tiroir-respace`, `tiroir-chienvert`; `~/.claude/context/tiroir.md`), so "many tiroirs per ThinkingToo member" is the real case, not a corner. Thierry's question on how ThinkingToo works with them became ticket 22; it does not change the answers below.

1. **A loose page moves to another tiroir on its own; a repo page never does.** A repo page goes where its root's tiroir says; to move it, the root's `.sheaf.toml` changes tiroir and the whole root moves (ticket 04). No single repo page goes against its root.
2. **Only the owner moves it, and stays its owner.** From the Sheaf ("Move to another tiroir…") or the owner's agent through the door's `move` naming a tiroir, and only to a tiroir where the owner has an account. It lands in the owner's loose root there, same folder. No ownership transfer: a page for Marina is moved to tiroir-0, then `Share with Marina` there; a page for a client likewise.
3. **What goes along: everything but the Share.** Versions, comments, the Write log lines (ticket 09) and the Archive or Keep mark (ticket 13) go; the Share does not, because members differ per tiroir: the page arrives as its owner's alone and the owner Shares it again. Nothing stays on the first tiroir but the Forward.
4. **In a browser, the old address redirects for ever** to the full address on the new tiroir. Someone without an account there gets that tiroir's Open WebUI sign-in and nothing more; the first tiroir shows no "moved to tiroir-0" page, which would tell where the page is to someone who may not open it.
5. **Through the door, the old path answers "moved" and writes nothing.** A `read` or `update` does not follow the Forward across tiroirs (the agent's token is per tiroir). The answer carries the new address, the tiroir, who moved it and when, and what to do, written for the user, by who asks:
   - a laptop with a token for that tiroir: `sheaf` sends there itself and prints that it did;
   - a laptop without one: "This page was moved to tiroir-0 by Thierry on 15/11. To keep working on it: `sheaf connect tiroir-0`. No account there? Ask Thierry for one, or to share it.";
   - Claude.ai, ChatGPT, the Open WebUI assistant (they cannot reach the other tiroir): "Moved to tiroir-0 by Thierry on 15/11; I can no longer open it from here. Ask Thierry to move it back, or for an account on tiroir-0."
   The same facts go to the first hub's Diagnostics log, so who still knocks at the old address is known.
6. **The two hubs talk directly**, over Tailscale, the first one as a tiroir, not as a member. It sends one bundle: file, versions, comments, Write log lines, mark. The receiving hub finds the owner among its Open WebUI users by email and refuses when there is none. The Forward is written only once the receiving hub confirms, so a failed transfer leaves the page where it was. Not through the laptop (download and re-upload would lose versions and comments).
7. **A whole root moved (ticket 04) uses the same channel.** When a `.sheaf.toml` changes tiroir, the next render report goes to the new tiroir, which makes its own repo clone (ticket 14); the old hub sees the change on its pull, sends each page's comments and versions by the channel of 6, writes a Forward per page and puts its clone to sleep.
8. **Tells follow the page when the laptop can.** The sheaf mod long-polling the old tiroir's door (ticket 18) sees the "moved" answer and also long-polls the new tiroir's door, if the laptop has a token for it. Without one, Tells pressed there do not arrive, and the page says so beside the button ("this session does not listen to tiroir-0").

New in `GLOSSARY.md`: **Move** and **Forward** extended across tiroirs. Surfaced: ticket 22 (ThinkingToo and many client tiroirs).
