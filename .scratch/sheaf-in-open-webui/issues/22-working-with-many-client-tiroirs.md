# 22: How a ThinkingToo member works with many client tiroirs: where the pages for a client live, and how the member reads them

**Type:** grilling
**Status:** open
**Blocked by:** none
**Map:** ../map.md

## Question

Raised by Thierry during ticket 21. Client tiroirs already exist (Avetta, Respace, Chienvert; Respace's and Chienvert's records still live inside the `thinkingtoo` repo under `clients/<name>/tiroir`), and every client may get one, holding what is client-facing. Thierry's first idea: a repo per client (say Klium), and the agent working in `thinkingtoo` puts only client-facing pages there. Then: how does a ThinkingToo member read and comment on what is on the client tiroirs, with many clients, without opening one Sheaf per client?

This reopens two points of ticket 04 and one of ticket 16:
- ticket 04 point 1: a root goes to one tiroir only;
- ticket 04 point 5: one Sheaf per tiroir, no view across tiroirs, argued from "pages on another tiroir are few", which a tiroir per client makes false;
- ticket 16: the owner's agent may Share on `create`; on a client tiroir that Share reaches the client, which by Thierry's rules is his own hand.

Ways in, from ticket 21: (a) one sign-in per client tiroir, a Sheaf each; (b) the client repo's pages live on two tiroirs at once, tiroir-tt for the team and the client's for the client, git keeping them in step since comments are in the file (ticket 03), each tiroir's clone committing page saves (ticket 14); (c) tiroir-tt's Sheaf shows the client tiroirs' pages read through, hub to hub (the channel of ticket 21). Also open: who has accounts on a client tiroir (the ThinkingToo team?), where client-facing pages are written from (the `thinkingtoo` repo vs the client repo), and what a client's member sees of the team's comments.
