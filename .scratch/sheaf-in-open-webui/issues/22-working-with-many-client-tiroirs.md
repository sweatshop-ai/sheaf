# 22: How a ThinkingToo member works with many client tiroirs: where the pages for a client live, and how the member reads them

**Type:** grilling
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Raised by Thierry during ticket 21. Client tiroirs already exist (Avetta, Respace, Chienvert; Respace's and Chienvert's records still live inside the `thinkingtoo` repo under `clients/<name>/tiroir`), and every client may get one, holding what is client-facing. Thierry's first idea: a repo per client (say Klium), and the agent working in `thinkingtoo` puts only client-facing pages there. Then: how does a ThinkingToo member read and comment on what is on the client tiroirs, with many clients, without opening one Sheaf per client?

This reopens two points of ticket 04 and one of ticket 16:
- ticket 04 point 1: a root goes to one tiroir only;
- ticket 04 point 5: one Sheaf per tiroir, no view across tiroirs, argued from "pages on another tiroir are few", which a tiroir per client makes false;
- ticket 16: the owner's agent may Share on `create`; on a client tiroir that Share reaches the client, which by Thierry's rules is his own hand.

Ways in, from ticket 21: (a) one sign-in per client tiroir, a Sheaf each; (b) the client repo's pages live on two tiroirs at once, tiroir-tt for the team and the client's for the client, git keeping them in step since comments are in the file (ticket 03), each tiroir's clone committing page saves (ticket 14); (c) tiroir-tt's Sheaf shows the client tiroirs' pages read through, hub to hub (the channel of ticket 21). Also open: who has accounts on a client tiroir (the ThinkingToo team?), where client-facing pages are written from (the `thinkingtoo` repo vs the client repo), and what a client's member sees of the team's comments.

## Grilling notes (Ottilie, in progress)

Facts (2026-11-16, read-only check): client tiroirs are chienvert, respace, avetta. Thierry is admin in Open WebUI on chienvert and respace; Sven and Hans have no account on any; avetta's users not checked live (ssh timed out), its door has Niccolò and Jessica. No sheaf module or proxy mode on any client tiroir.

Round 1 (Thierry):
- Q1: a repo per client (e.g. `klium`) holding only client-facing pages, its `.sheaf.toml` naming the client's tiroir; the client tiroir's GitHub App sees that repo only. Ticket 04 point 1 stands.
- Q2: on a tiroir marked as a client's, the agent never plain-Shares; it may only `Share with <ThinkingToo members>`; the Share that opens a page to the client is the member's hand.
- Q3: an internal comment is needed: the team comments on a client page without the client ever seeing it (reopens ticket 03's comments-in-the-file for this case).

Round 2 (Thierry):
- Q4: the internal comment lives on tiroir-tt, a team verso tied to the client page's address; it never reaches the client tiroir, the client repo or the client's memorizer. Name still open ("team comment" for now).
- Q5: the team reads client pages from tiroir-tt's Sheaf, a "Clients" folder read through hub to hub (ticket 21's channel), client comments and team comments together. Reopens ticket 04 point 5 for client tiroirs only.
- Q6 reopened by Thierry: a client may have a brain on their tiroir; every user's brain is private and the agency must never read it.

Fact found while checking Q6 (2026-11-16): on tiroir-chienvert and tiroir-respace Open WebUI runs with no `ENABLE_ADMIN_*` env set, so its defaults hold: `ENABLE_ADMIN_CHAT_ACCESS`, `ENABLE_ADMIN_EXPORT` and `ENABLE_ADMIN_WORKSPACE_CONTENT_ACCESS` are all True (`env.py:371`, `config.py:2082-2084` in the container). Thierry is admin on both, so the admin UI today opens the client users' chats.

Round 3 (Thierry):
- Q6a: a ThinkingToo member on a client tiroir is a `user`, never `admin`; the Sheaf has no admin override; they see the client repo's root and what a client member Shared with them, nothing else; the hub-to-hub channel from tiroir-tt carries only what that member may open. The client's loose pages, chats and brain are never reachable.
- Q6b: closing Open WebUI's admin access on the client tiroirs is a follow-up outside the map: `.scratch/follow-ups/client-tiroirs-open-webui-admin-reads-client-chats.md`.
- Q6c: the spec states the client tiroir privacy rule: no agent and no ThinkingToo member reads a client user's brain, chats or private pages; the tools offer no way to, and stages never read user data. The agency operates the box as root, so the technical guarantee ends there, and the spec says so.

Round 4 (Thierry):
- Q7: a client tiroir is administered by a service account `ops@<client>.tiroir.me`, admin, password in the keyring, used only by stages.
- Q8: Thierry names a member for a client; an agent creates the account through a stage; the list lives in the tiroir's record (`devices.yaml`). An account is not a message to the client.
- Q9: the client's brain indexes only the pages opened to the client with plain Share, never drafts (owner-only or Shared with the team).
- Q10: the internal comment is a **Team comment** (`GLOSSARY.md`).
