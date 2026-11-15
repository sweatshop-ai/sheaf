# 20: Making folders and moving pages from the Catalog after the first version

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 06 kept folders and moves out of the first version: a folder is the path on disk, and in a repo a move is a rename commit that breaks links and the paths agents know. When moves come, are they for loose pages only (the `loose-<short>` root, where nobody else links in) or also for repo pages (a rename commit on the branch of ticket 14)? What happens to a moved page's address: does the old one forward to the new one (a record in the hub, as a root moved to another tiroir does in ticket 04), for how long, and how do links inside other pages and the paths an agent remembers find it? Who may move a page they do not own, a Shared one (ticket 16)? And can a member make an empty folder, or does a folder exist only when a page is in it?

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (one round; Q8 reworded twice).

Fact found first: "Move to" is already a word of the List (SPEC 9.10): the box a mail sheaf's Client section offers per candidate (`tiroir_mail_replies/sheaves.py`, `MOVE_TO`). AgentView has a third, unrelated move: "move this session to…" a project (`agentview/hand.py`, `move`).

1. **Only loose pages move from the Sheaf.** A repo page moves with git, a rename commit made by a session, as it is deleted with git (ticket 13); the Sheaf shows what the repo holds. The Sheaf makes no rename commit.
2. **A move stays inside its root.** No move from loose to repo, repo to loose, or between two roots; bringing a loose page into a repo is a session's `git add`.
3. **The old address forwards to the new one, for ever**: a forward record in the hub (old path → new path), as for a root moved to another tiroir (ticket 04), never expiring. The page's versions, comments, archive or Keep mark (ticket 13) and Share (ticket 16) go with it. No fixed-id address: a folder stays the path (ticket 06).
4. **Nothing is rewritten; the forward resolves.** Links inside other pages are left as they are. The library door, read or `update` on an old path, follows the forward and answers with the new path, so the agent learns it. When the hub sees a git rename on a repo clone's pull, it writes the same forward record and carries versions and comments over.
5. **Only the owner moves**: from the Sheaf, or the owner's agent through a door `move`. A move changes no one's visibility and the forward breaks nothing, so unlike `delete` (which the door does not have) an injected text can do no real harm with it. A recipient of a Shared page sees it under "Shared with me" and does not move it.
6. **A folder exists only while a page is in it.** "New folder" is a path typed in the move dialog: made when the first page arrives, gone with the last. Same for loose and repo roots (git keeps no empty folder).
7. **Renaming or moving a whole folder** (in the loose root) is moving each of its pages, each with its forward.
8. **The name is Move**, the action on a Sheaf row ("Move…") and the door's `move`. To end the clash, the List's "Move to <slug>" is renamed **Belongs to <slug>** (`- [ ] Belongs to klium (ref <thread>)`): the slug is whatever the thread belongs to (a client, a project, a team), "client" and "reassign" were turned down as too narrow and as clashing with an issue's assignee. That rename is work outside this map: `.scratch/from-render-doc/168-rename-move-to-belongs-to.md`. AgentView's session move is not part of this map.

New terms in `GLOSSARY.md`: **Move** (of a rectoverso), **Forward**; **Move to** renamed **Belongs to**.
