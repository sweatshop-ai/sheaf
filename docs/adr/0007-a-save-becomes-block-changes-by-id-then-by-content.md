# A save becomes block changes by id first, then by content

Status: accepted (2026-11-25, block-editor design, decision 14). Amends the Consequences of ADR 0004.

A page save carries the whole Markdown of the rectoverso **and the id each block held when the page loaded** (none for a block the page created). Core parses the Markdown into the block tree, matches each block to the base's tree by that id, and falls back to comparing content only where an id is missing or does not line up with its parse. From the match it derives the **block changes** of the save: insertions, moves, removals and edits. Those changes drive the capability check, ADR 0004's rebase rule and conflicts, and the queue of ADR 0006. The reason is that plain blocks store no id, so from Markdown alone a block that is moved and edited in one save is indistinguishable from a removal plus an insertion, which orphans its comments and turns another member's edit of it into a false conflict. The editing engine (ADR 0003) keeps a node's attributes through a drag, so the page already knows which block is which.

## Matching

- **By id.** Ids travel beside the Markdown, never inside the `.md`. When two blocks arrive with the same id (TipTap copies attributes when Enter splits a block), the first keeps it and the others count as new.
- **Equality.** Two versions of a block are equal when their pandoc AST is equal, so pandoc's cosmetic rewrites (fence length, table column padding) are no change. An unchanged block is written back with the source's original bytes. A plain block's content-derived id (ADR 0004) is hashed over the same AST.
- **Fallback by content.** Blocks with an equal AST are matched first; their order inside each container is aligned, and an equal block outside that order is a move. Leftover blocks between two matched blocks of the same container are paired by word similarity (threshold 0.5, the existing merge's rule) and count as edits. Whatever stays unpaired is a removal or an insertion.
- **Kinds of change.** A change of Block type or of attributes is an edit of the same block. A split is an edit of the first block plus an insertion; a join is an edit of the upper block plus a removal of the lower. A block dragged into or out of a container is a move with a new parent, checked against the target container's insertable types.

## Rebase and clashes

When the base is stale, core rebases the save's changes onto the current version as ADR 0004 allows:

- **Placement.** An inserted or moved block goes after its preceding sibling in the current version; if that sibling is gone, after the nearest earlier surviving sibling; if none survives, at the start of the container. Only a container that is gone makes the save a conflict.
- **Clashes on one block.** Edit against move: both apply, the edit at the new place. Move against move: the later save wins, no conflict. Removal against edit: conflict. Edit against edit: conflict.
- **A page never conflicts with itself.** The hub records which page session (request id) wrote each base; changes made by the same page's earlier saves never count as changed since the base. This replaces the existing merge's text matching of its own earlier saves (`saved`).

## Refusal

A save that changes a block it may not (an edit to a Stub or to locked raw HTML, a Rich block inserted or moved where its container does not allow it) is **refused** whole, naming the block and the reason; nothing is written. The page keeps the member's text and shows the reason. This replaces the existing merge's path that wrote the rest and put the forbidden block's text in a note, so a page save and an agent's `edit_blocks` end in the same one of three outcomes.

## Queued writes

A collapsed queue entry (ADR 0006: one member's consecutive writes during an outage, latest tree on the oldest base) gets its changes by matching the oldest base against the latest tree, with the same rules. The hub gives ids to queued blocks at once, so the page's ids stay valid between saves, and keeps a map from them back to the oldest base's ids. Intermediate states are forgotten: a block inserted and removed again leaves nothing, a block edited and changed back is unchanged.

## Considered options

- **Markdown only, as ADR 0004 first said.** Rejected: moves are guessed from text, and a block moved and edited together becomes remove plus insert.
- **Normalised text instead of the AST.** Rejected: every cosmetic quirk of pandoc would need its own rule, and a missed one shows up as a false edit or a false conflict.
- **A conflict on any change of a neighbour, or on every clash.** Rejected: concurrent editing would produce conflicts where no text is at risk. Only clashes that could lose text are conflicts.
- **The page waiting for each save's answer.** Rejected in favour of tracking the writer per base: a slow connection would delay autosave, and a lost answer would block saving until a reload.
- **Replaying queued writes one by one.** Rejected: more commits and more conflicts, for intermediate states nobody asked to keep.
- **Special records for split and join.** Rejected: a rare case, and edit plus insert or edit plus removal already keeps a concurrent edit from being lost.

## Consequences

- ADR 0004's line "the page sends whole Markdown and core finds the changed blocks" now reads: the page sends whole Markdown and the ids it holds, and core finds the block changes as above.
- The existing `merge_edits` alignment survives only as the content fallback; its `saved` and locked-note paths go.
- The hub keeps, per base, the page session that wrote it, and for a remote source's queue an id map back to the oldest base.
- Comments (ticket 16) and versions (ticket 17) of the block-editor design build on these block changes.
