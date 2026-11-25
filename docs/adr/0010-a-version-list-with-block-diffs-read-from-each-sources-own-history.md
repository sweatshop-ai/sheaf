# A version list with block diffs, read from each source's own history

Status: accepted (2026-11-25, block-editor design, decision 17). Amends ADR 0006 (the protocol gains an optional history call).

Every rectoverso gets a **version list** and a **Compare mode** that shows, block by block, what a version changed, and either a whole version or a single Block can be restored from it. The list is read from history that already exists, and sheaf adds no history store of its own: in a root that commits, the git commits that touch the file; in a root that does not commit, the Versions store (SPEC 7.4); for a remote source, the Source service's optional `versions` call, or else the reads the hub kept. The reason is that sheaf has no user-facing history today. A root that commits already writes every save as a commit (SPEC 8.11), and Astro and WordPress keep their own history (git commits, post revisions). A second copy kept in the hub would drift from the one a source's owner trusts.

## Decisions

- **Where versions come from.** In a committing root, each commit that changes the file is a version, with author and time taken from git. In a non-committing root, the Versions store's entries are the versions, so the list goes back only as far as that store's limits (60 per page, 7 days), and the list says so. For a remote source, the versions come from `versions(document)` when the Source service declares it. Otherwise they are the reads and writes the hub kept, within the same limits.
- **Grouping, on the Google Docs model.** Consecutive saves with no gap longer than 10 minutes form one row, which lists every author who saved in it. An arrow expands the row into its single saves. Any version can be **named**: by a member in the list, or by an agent through the `note` of `edit_blocks`. A filter shows named versions only. A name lives where the source can hold it: as a git commit trailer in a committing root, and through the protocol when the service declares named versions. Anywhere else it lives in the hub's state beside the Versions store, and a named version is kept like a pin, outside the 60 / 7-day pruning.
- **Comment saves are no versions.** A save that changes only comment markup (a comment, reply, resolve or orphaning in a Markdown file) is no row in the list. Comment markup is stripped before two versions are compared, so it never appears as a change. Compare mode hides comments.
- **Compare mode, inline on the page.** Selecting a version shows the rectoverso as it was then, in the page's own look (ADR 0008). By default the changes shown are those against the version before it, as in Google Docs. A switch compares the selected version with the current page instead, which is the view a restore needs. Changes are the Block changes of ADR 0007, found by the same match: an inserted Block is marked inserted; an edited Block shows a word diff inside it, and a changed type or attribute is named; a moved Block shows at its new place, marked "moved from" its old one; a removed Block shows as a ghost where it was. Each change carries its author's colour, stable per member and per agent token, and the kind of change is shown by the marker's shape, never by colour alone. Compare mode is editor chrome: it is not in print, the share copy or the PDF.
- **Restore writes forward.** Restoring a whole version, or a single Block from the diff (bring back a removed Block, undo one edit), is a new save through ADR 0007, so history is never rewritten. Comments follow ADR 0009's rules, and a remote source receives an ordinary `write`.
- **Agents.** `blocks` takes an optional `since` (a base the agent holds) and returns the Block changes from that base to the current version: inserted, moved, removed or edited, each with id and Block type. A base that is no longer known answers "unknown base, read the page again". The version list and the restore stay on the page; agents restore with `edit_blocks`.
- **Protocol (amends ADR 0006).** A Source service may declare `versions`: `versions(document)` lists versions with id, author, time and an optional name, and `read(document, version)` returns that version's block tree in the wire form of ADR 0004. A service may also declare that it stores names: `name(document, version, name)`. The hub groups and compares; the service only lists and reads. A service that declares none of this still works, with the shorter list above.

## Considered options

- **Changes since the member's last visit only, with no list and no restore.** Rejected by Thierry: the list, restore and named versions are what members know from Google Docs.
- **A history store of its own in the hub, for every kind of root.** Rejected: a committing root already has git, and a remote source has its own history. A third copy costs disk and can disagree with the source.
- **Text diffs of the Markdown (git) only.** Rejected: a moved Block shows as a removal plus an insertion, and the fenced-div syntax shows through.
- **Every save as its own row, or named versions only.** Rejected: autosave makes hundreds of rows in half an hour, and listing only named versions hides everything nobody named.
- **Always compare with the current page, or let the member pick any two versions.** Rejected as the default: "what did this version change" is the common question. Comparing with now is a switch.
- **Colours by kind of change.** Rejected: with several authors the question is who changed it; the shape of the marker already gives the kind.
- **Comment saves as versions labelled "comments".** Rejected: they would bury content versions under discussion traffic, and comments already have their own threads.

## Consequences

- The hub reads git history per file in committing roots. This is new: it only ever wrote commits before.
- In a non-committing root, and on a remote source without `versions`, the list is short. Rooting a folder in git is the way to a long history.
- The Versions store gains named versions that are exempt from pruning. Names and pins are kept in the hub's state, backed up with it.
- The page gains a version list panel and Compare mode. The spec fixes the panel's layout and the colour palette.
- `blocks` gains `since`. The MCP tool list (decision 08) stays otherwise unchanged.
