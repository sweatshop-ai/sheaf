# 06: What a folder of the Catalog is

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** 05
**Map:** ../map.md

## Question

The Catalog shows every page of a user in folders. What is a folder: the path on disk (root, repo, sub-folder), the client and project the List already uses (`<client>/<project>`), the session that made the page, or folders the user makes and moves pages between? How does the Catalog sit beside the List in Open WebUI: one entry or two?

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (one round, all six recommendations accepted).

1. **A folder is the path on disk.** The top level is the root (the repo's or folder's name: `tiroir-sheaves`, `private-thierry`, `sheaf`, `.claude`), below it the root's own sub-folders as they are. Not `<client>/<project>` (the List's grouping; in the list's root it is the path anyway), not the session that made the page: the session is a field of the page's row (ticket 07).
2. **The Catalog is the hub's index page (SPEC 8.6), drawn as a folder tree**, filtered per member as 9.9 already filters it. It holds every `.md` of each of the member's roots, not only rendered or opened ones. Dot-folders stay out as today (`.scratch/`, `.claude/` included); their pages still open at their address.
3. **Loose pages go in one root per member, `loose-<short>`**, in the folder the agent names on `create` (e.g. `thinkingtoo/avetta/`); when it names none, the month's folder (`2026-11/`).
4. **No folders made and no pages moved from the Catalog in the first version**, not even for loose pages: in a repo a move is a rename commit that breaks links and the paths agents know. Moved to Not yet specified.
5. **Two entries in Open WebUI's sidebar**: "Actions" (exists, mounts the List) and a new one for the Catalog. Its label waits on the name of the whole.
6. **Pages another member Shared with you (9.11)** sit in a top-level "Shared with me" folder, one sub-folder per owner, not in their root's place (private roots are not yours to browse).
