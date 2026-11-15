# 14: Which repos get a clone on the tiroir, and how

**Type:** grilling
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 05 put a repo page's original in git, with a clone of the repo on the tiroir that commits page saves on the working branch. Which repos get that clone: every repo a session renders a page from (made the first time a page from it arrives), or only repos the member adds? Who adds one and how (a command on the laptop, the Catalog, the tiroir's config), with what GitHub credential on the tiroir (a deploy key per repo, one machine user)? And how is a large repo such as the monorepo cloned for its pages only (sparse checkout of the folders that hold pages, a shallow clone), and what happens when a page sits outside that set?
