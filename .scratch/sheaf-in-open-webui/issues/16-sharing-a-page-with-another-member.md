# 16: Sharing a page with another member of the tiroir, and what each member sees

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

SPEC 9.11 defines visibility (a page is its owner's alone until Shared), ticket 04 made that the rule on every tiroir and let the agent Share through front matter, ticket 06 put pages Shared with you in a "Shared with me" folder per owner, and ticket 14 records a repo page's owner in a hub record. What is left for a tiroir with several members (Sven and Hans on tiroir-tt): who may Share a page (its owner only, or anyone who can edit it), with whom (one member, several, every member of the tiroir; never someone outside it?), with which right (read, comment, edit, Tell), from where (the Catalog row, the page, the agent's front matter, the door's tools), how a Share is taken back, and what a member sees of a repo clone whose other pages belong to someone else. Also: does a Shared page tell its owner who opened or changed it, and does a Tell pressed by a recipient go to the owner's agent session or the recipient's own agent (SPEC 9.8 says a member only ever Tells their own agents)?

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (one round, all seven recommendations accepted).

Fact found first: SPEC 9.11's Share opens a sheaf to "every member whose roots hold it". A loose page lives in its member's `loose-<short>` root (ticket 06), which no one else holds, so today Share would open it to nobody.

1. **Two forms of Share.** `- [ ] Share` opens a loose page to every member of the tiroir, and a repo page as today (the members whose roots and project hold it, 9.11, 8.12). `- [ ] Share with hans, sven` opens it to the named members only (by `short`), on loose and repo pages alike; it matters on client tiroirs with many members.
2. **What a recipient may do**: read, comment, save, tick actions and Tell their own agent, as on a page open to the project today. Share and its withdrawal stay the owner's alone. No read-only level in the first version.
3. **Never outside the tiroir.** Share reaches members only; for a client or anyone else there is the Share copy (`sheaf --share`), read-only and without comments.
4. **Where from**: the Catalog row (a Share button that writes the Share line), the page (the box), and the agent. The owner's own agent (a door token bound to the owner) may Share only on `create` of a new page, never on `update` of an existing private one: door tokens read untrusted text, so an injected text cannot open a page that already holds private work. The row shows "shared by <agent>", and the owner withdraws it at any time.
5. **Other members' pages in a repo clone** are invisible to a member until Shared (the owner comes from ticket 14's hub record); a folder holding no page the member may see does not appear in their Catalog.
6. **A recipient's Tell** goes to the recipient's own agent (9.8). The owner's session name shows on the row but cannot be Told by a recipient; to reach the owner, a recipient comments with `@<owner>`.
7. **Who changed what**: the Catalog row's last write (ticket 09) tells the owner; no notifications in the first version. A recipient sees a "new" dot on the page in "Shared with me" (ticket 06).

Consequences for the spec: 9.11's Share grows a named form, and a loose root's plain Share means the whole tiroir; withdrawing a named Share is the owner unticking it or editing the names. A recipient's agent sees a Shared page because a token never exceeds its member's access (9.11), and 9.11's "door writes ignore `shared`" gains the one exception of point 4.
