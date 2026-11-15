# 13: How long a page lives in the Catalog

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Every page an agent session renders now goes to the tiroir (charting), and Thierry sees most of them as temporary, tied to one session. A loose page has no repo to fall back on. Does a page stay in the Catalog forever, get archived (hidden from the default view, still openable at its address) after some rule (age, session ended, no comment open), or expire and get deleted? Who or what decides: the agent that made it, the member, a default per root? Does the answer differ for repo pages (git keeps them anyway) and loose pages?

## Answer

Grilled with Thierry, 2026-11-15 (Ottilie), two rounds, every point as recommended.

- **A repo page follows git.** The Catalog shows what is in the repo: the page lives as long as its file, and is deleted or moved with git. Sheaf archives and deletes nothing in a repo.
- **A loose page is archived, never deleted by a rule.** After 30 days with no write and no comment, and no comment open, it leaves the Catalog's default view; it still opens at its address and shows in an "Archived" view. The 30 days are a default the loose root's `.sheaf.toml` can change (`archive_after`), the same on every tiroir.
- **The agent and the member can change a page's fate.** The agent can say keep on `create` (`sheaf FILE.md --keep`): never archived. The member can, from the Catalog, Archive now, Restore, or Keep. This is a mark, not a move, so ticket 06's "no moves in v1" holds. The mark lives in the root's `.sheaf/`, never in the page's text (a mark that wrote the page would itself count as a write).
- **An archived page comes back on its own** when it is written or gets a new comment. Opening it does not.
- **Only the member deletes, from the Catalog, into a trash.** Delete moves the page to the root's `.sheaf/trash/` for 30 days, then it is gone. The library door has no `delete`: no agent, Claude.ai or ChatGPT deletes a page.
- Follows for the spec: the archive state is the owner's; how an archived page shows to a member it was Shared with goes with sharing in Not yet specified.
