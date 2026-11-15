# 22: How a ThinkingToo member works with many client tiroirs: where the pages for a client live, and how the member reads them

**Type:** grilling
**Status:** resolved (2026-11-16)
**Blocked by:** none
**Map:** ../map.md

## Question

Raised by Thierry during ticket 21. Client tiroirs already exist (Avetta, Respace, Chienvert; Respace's and Chienvert's records still live inside the `thinkingtoo` repo under `clients/<name>/tiroir`), and every client may get one, holding what is client-facing. Thierry's first idea: a repo per client (say Klium), and the agent working in `thinkingtoo` puts only client-facing pages there. Then: how does a ThinkingToo member read and comment on what is on the client tiroirs, with many clients, without opening one Sheaf per client?

This reopens two points of ticket 04 and one of ticket 16:
- ticket 04 point 1: a root goes to one tiroir only;
- ticket 04 point 5: one Sheaf per tiroir, no view across tiroirs, argued from "pages on another tiroir are few", which a tiroir per client makes false;
- ticket 16: the owner's agent may Share on `create`; on a client tiroir that Share reaches the client, which by Thierry's rules is his own hand.

Ways in, from ticket 21: (a) one sign-in per client tiroir, a Sheaf each; (b) the client repo's pages live on two tiroirs at once, tiroir-tt for the team and the client's for the client, git keeping them in step since comments are in the file (ticket 03), each tiroir's clone committing page saves (ticket 14); (c) tiroir-tt's Sheaf shows the client tiroirs' pages read through, hub to hub (the channel of ticket 21). Also open: who has accounts on a client tiroir (the ThinkingToo team?), where client-facing pages are written from (the `thinkingtoo` repo vs the client repo), and what a client's member sees of the team's comments.


## Answer

Resolved 2026-11-16 by Ottilie grilling with Thierry (four rounds; Q6 reopened by Thierry on the client's brain). The round notes below keep the questions as asked.

Facts found first (read-only, 2026-11-16): three client tiroirs exist; no sheaf module runs on any; the ThinkingToo team has few accounts on them. The detail, with the hosts and the people, is in a private follow-up (below), not in this public repo.

1. **A client's pages are written in a repo per client** (`klium`), holding only what is client-facing. Its `.sheaf.toml` names the client tiroir. The client tiroir's GitHub App (ticket 14) is installed on that repo only, never on `thinkingtoo`. Internal work stays in `thinkingtoo` on tiroir-tt. Ticket 04 point 1 stands: a root goes to one tiroir.
2. **On a client tiroir the agent never opens a page to the client.** A tiroir's record marks it as a client's (`client: true` in `devices.yaml`). There the owner's agent may `Share with <ThinkingToo members>` on `create`, never plain Share. Plain Share, which opens the page to the client's members, is the member's own hand from the Sheaf. Narrows ticket 16's agent Share.
3. **The team discusses a client page in Team comments, which the client never sees.** A Team comment lives on tiroir-tt, tied to the client page's address, on a team verso beside the client's. It never reaches the client tiroir, the client repo or the client's brain. Adds to ticket 03: comments stay in the file, Team comments are the one exception, and they are not in the client's file at all.
4. **The team reads every client from tiroir-tt's Sheaf.** A "Clients" folder holds one sub-folder per client tiroir, read through over the hub-to-hub channel of ticket 21. tiroir-tt keeps no copy. An opened client page shows the client's comments, written to the client tiroir under the member's name, and the Team comments, kept on tiroir-tt. One sign-in. Reopens ticket 04 point 5 for client tiroirs only.
5. **Tells follow ticket 18.** A Tell a ThinkingToo member presses goes to that member's own agent. A client member's Tell goes to the client's own assistant.
6. **Client tiroir privacy rule (goes into the spec).** Every client user's brain, chats and private pages are theirs alone: no agent and no ThinkingToo member reads them, the tools offer no way to, and stages never read user data. A ThinkingToo member on a client tiroir is an Open WebUI `user`, never `admin`. The Sheaf has no admin override: the member sees the client repo's root and what a client member Shared with them, and the hub-to-hub channel carries only that. The agency operates the box as root, so the technical guarantee ends there, and the spec says so.
7. **A service account administers each client tiroir**: `ops@<client>.tiroir.me`, admin, password in the keyring, used only by stages, with Open WebUI's three `ENABLE_ADMIN_*` off.
8. **Accounts on a client tiroir**: Thierry names a member for a client, an agent creates the account through a stage, and the list lives in the tiroir's record. An account is not a message to the client.
9. **The client's brain indexes only pages opened to the client** by plain Share. Drafts, owner-only or Shared with the team, reach the box with the git push but are never indexed.

New in `GLOSSARY.md`: **Client tiroir**, **Team comment**; **Default tiroir** carries the exception of 4. Follow-up outside the map, kept private in the `thinkingtoo` repo: `clients/follow-ups/2026-11-16-open-webui-admin-reads-client-chats.md` (Open WebUI's admin settings on the client tiroirs, the ThinkingToo accounts' role, the runbook default).

## Grilling notes (Ottilie, in progress)

Facts (2026-11-16, read-only check): no sheaf module or proxy mode on any client tiroir; who has which account is in the private follow-up named in the Answer.

Round 1 (Thierry):
- Q1: a repo per client (e.g. `klium`) holding only client-facing pages, its `.sheaf.toml` naming the client's tiroir; the client tiroir's GitHub App sees that repo only. Ticket 04 point 1 stands.
- Q2: on a tiroir marked as a client's, the agent never plain-Shares; it may only `Share with <ThinkingToo members>`; the Share that opens a page to the client is the member's hand.
- Q3: an internal comment is needed: the team comments on a client page without the client ever seeing it (reopens ticket 03's comments-in-the-file for this case).

Round 2 (Thierry):
- Q4: the internal comment lives on tiroir-tt, a team verso tied to the client page's address; it never reaches the client tiroir, the client repo or the client's memorizer. Name still open ("team comment" for now).
- Q5: the team reads client pages from tiroir-tt's Sheaf, a "Clients" folder read through hub to hub (ticket 21's channel), client comments and team comments together. Reopens ticket 04 point 5 for client tiroirs only.
- Q6 reopened by Thierry: a client may have a brain on their tiroir; every user's brain is private and the agency must never read it.

Fact found while checking Q6 (2026-11-16): recorded in the private follow-up named in the Answer.

Round 3 (Thierry):
- Q6a: a ThinkingToo member on a client tiroir is a `user`, never `admin`; the Sheaf has no admin override; they see the client repo's root and what a client member Shared with them, nothing else; the hub-to-hub channel from tiroir-tt carries only what that member may open. The client's loose pages, chats and brain are never reachable.
- Q6b: Open WebUI's admin settings on the client tiroirs are a follow-up outside the map, kept private (see the Answer).
- Q6c: the spec states the client tiroir privacy rule: no agent and no ThinkingToo member reads a client user's brain, chats or private pages; the tools offer no way to, and stages never read user data. The agency operates the box as root, so the technical guarantee ends there, and the spec says so.

Round 4 (Thierry):
- Q7: a client tiroir is administered by a service account `ops@<client>.tiroir.me`, admin, password in the keyring, used only by stages.
- Q8: Thierry names a member for a client; an agent creates the account through a stage; the list lives in the tiroir's record (`devices.yaml`). An account is not a message to the client.
- Q9: the client's brain indexes only the pages opened to the client with plain Share, never drafts (owner-only or Shared with the team).
- Q10: the internal comment is a **Team comment** (`GLOSSARY.md`).
