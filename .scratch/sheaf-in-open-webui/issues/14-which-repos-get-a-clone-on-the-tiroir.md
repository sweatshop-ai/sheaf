# 14: Which repos get a clone on the tiroir, and how

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 05 put a repo page's original in git, with a clone of the repo on the tiroir that commits page saves on the working branch. Which repos get that clone: every repo a session renders a page from (made the first time a page from it arrives), or only repos the member adds? Who adds one and how (a command on the laptop, the Catalog, the tiroir's config), with what GitHub credential on the tiroir (a deploy key per repo, one machine user)? And how is a large repo such as the monorepo cloned for its pages only (sparse checkout of the folders that hold pages, a shallow clone), and what happens when a page sits outside that set?

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (two rounds, every recommendation taken).

Facts found first: in a month the laptop hub rendered pages from 12 distinct repos (thinkingtoo 5, sweatshop-ai 3, tiroir 3, sven01 1; `~/.local/state/sheaf/roots.json`, 80 of 119 roots being deleted worktrees). tiroir-tt already holds deploy keys for `thinkingtoo/tiroir-sheaves` and the GitHub App `tiroir`, whose installation token (renewed by a root timer for the hub) reaches thinkingtoo repos only (`tt-tiroir/README.md`, `wizard/record-setup.sh`). The monorepo's `.git` is 286 MB.

1. **A repo clone is made automatically** the first time a render report (ticket 11) arrives for a page of a repo the tiroir has no clone of. Nobody adds a repo by hand.
2. **The credential is one GitHub App per tiroir** (tiroir-tt's existing `tiroir` App; tiroir-0 gets its own), installed on each org or account with "selected repositories". Adding a repo is one click on GitHub by whoever owns it (Thierry for thinkingtoo, sweatshop-ai, tiroir; Sven for `sven01`); the token renews on its own. No deploy key per repo, no machine user.
3. **One clone per repo per tiroir**, whoever's pages it holds. Ownership is per page, not per clone: a page is its member's alone until Shared (ticket 04).
4. **The owner is in a hub record** (repo + path → member), filled by the first render report. The hub writes nothing into the repo for it; an `owner` or Share in the page's front matter, when present, wins.
5. **Every clone is blobless and sparse** (`--filter=blob:none`, sparse checkout of the folders that hold pages); the hub widens the sparse set itself when a page arrives from a new folder, so no page sits outside it. One way for every repo, large or small.
6. **Branch:** page saves are committed on `dev` where it exists; otherwise on the branch the repo's `.sheaf.toml` names; with neither, the page on the tiroir opens read-only (comments included) with a line saying why. The hub never guesses whether a default branch deploys. Consequence: a repo without `dev` (sheaf, `~/.claude`) needs one line in its `.sheaf.toml` to be editable on the tiroir.
7. **Unreachable repo** (App not installed on it, commit not pushed, no remote): `sheaf FILE.md` falls back to the laptop hub with a loud warning, as when the tiroir is offline (ticket 12); when the App is what is missing it prints the link that adds the repo to the installation, and the next render clones.
8. **A clone follows its pages** (ticket 13): when every page in it has been archived for 30 days it stops pulling and its sparse set shrinks; the pages still open at their last text. Only the member deletes a clone; no rule does.

Spec note: a repo clone is a shared root, not a member's private root (SPEC 9.9), so a page's privacy there rests on the hub record of point 4, not on the root. A repo that is a member's private root on the same tiroir gets no clone.

New term in `GLOSSARY.md`: **Repo clone**.
