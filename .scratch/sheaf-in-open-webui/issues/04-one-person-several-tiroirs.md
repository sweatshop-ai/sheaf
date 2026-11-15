# 04: A person who works on several tiroirs: where do their pages go

**Type:** grilling
**Status:** resolved
**Blocked by:** 01
**Map:** ../map.md

## Question

Thierry works for ThinkingToo (tiroir-tt), on tiroir itself, on his own things, and through his boss sessions (`~/.claude/pm`); tiroir-0 is only his memory. Marina only uses tiroir-0. When one person's sessions produce pages for more than one domain, which tiroir does each page go to, decided by whom (the root, the client, the session, the person), and how does the person find all their pages again? Thierry asked for a dedicated session on this and its implications.

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (two rounds plus one clarification).

1. **The root decides** which tiroir a page goes to, not the session, the page or the client. The tie is optional and lives in the root config (`.sheaf.toml`), so whoever clones the repo inherits it.
2. **A root that names no tiroir** (a new repo, `~/.claude/pm`, a scratch folder) sends its pages to the person's **default tiroir**, written once in the laptop's sheaf config: tiroir-tt for Thierry, tiroir-0 for Marina. The agent asks nothing.
3. **Thierry's non-ThinkingToo pages** (the tiroir product, sheaf, personal things) go to his private root on tiroir-tt: one home, as charting decided. tiroir-0 stays his memory.
4. **Visibility is the same rule on every tiroir**: a page is its owner's alone until Shared (SPEC 9.11), also a page Thierry makes for Marina in a root tied to tiroir-0. The agent can Share it through front matter when the page is for her.
5. **Finding pages again: one Catalog per tiroir**, no federation. Pages on a tiroir other than the default are few (work for Marina) and are opened there.
6. **A root moved to another tiroir works like Google Drive**: its pages move with their versions and comments, and the old address leads to the new one.

New terms in `GLOSSARY.md`: **Root's tiroir**, **Default tiroir**. Left as fog on the map: moving a single page to another tiroir (and what happens when that goes against its root's tiroir), and how an old address forwards across tiroirs.
