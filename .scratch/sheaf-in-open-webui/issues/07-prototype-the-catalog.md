# 07: The Catalog inside Open WebUI, as a rough prototype

**Type:** prototype
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** 06
**Map:** ../map.md

## Question

What should the Catalog look and behave like inside Open WebUI, opened from its sidebar: the folder tree, a page's row (title, when, which session), opening a page, and how it reads beside Open WebUI's own chats and the List? A throwaway prototype for Thierry to react to, linked from this ticket.

## Prototype

Built 2026-11-15 by Ottilie: branch `prototype/07-catalog` (commit 6877ce2, pushed, never merged), file `.scratch/sheaf-in-open-webui/prototype/catalog.html`. One HTML file, made-up data, an imitation of Open WebUI's sidebar around it; switch with `?variant=` or the pink bar (← →).

- **A, Finder:** the Catalog takes the main pane; folder tree on the left, a table on the right (title, folder, session, changed, comments); a page replaces the pane with a "← Catalog" button.
- **B, In the sidebar:** the Catalog replaces the chat list in Open WebUI's own sidebar as a tree of titles; the page fills the main pane and the tree stays.
- **C, Recent first:** pages grouped by day like Open WebUI's chats (Today, Yesterday, …), folders a second tab of cards per root.

Waiting on Thierry's reaction; the answer is recorded when he has picked.
