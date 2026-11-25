# Block comments are stored where the block is, and follow its block changes

Status: accepted (2026-11-25, block-editor design, decision 16)

A **Block comment** (a Comment on a whole Block, for an image, an App, columns or any Block whose remark is about the whole) is stored the way the page's other comments are. In a Markdown file it is an inline `sheaf-comment` on its own line right after the Block, after the image line or the closing `:::`, inside the Container when the Block sits in one, with a new head field `on=block` in place of `quote`. For every source reached through a Source service, it goes to the hub's **Comment store** keyed by document and block id, beside that source's text comments. The reason is that position already anchors a comment in a file: a file keeps its comments when it is copied, read by an agent or edited by hand, and a plain Block's id is derived from its content (ADR 0004), so an id written into the file would go stale on the Block's first edit.

## Decisions

- **Every Block takes one.** The block toolbar offers "Comment on block" on every Block, text Blocks included; a text selection still makes today's text comment. Checked on pandoc 3.9: an `on=block` comment inside a column and after a closing fence survives a `gfm+fenced_divs` round-trip, only the fence lengths change (ADR 0004 counts that as no change).
- **Inline content.** A button, or an image inside a line or a table cell, has no id (ADR 0004). Clicking it in edit mode offers "Comment", which makes an ordinary text comment whose `quote` is the button label or the image's alt text, stored right after it.
- **Block changes carry comments** (ADR 0007). A move, also across Containers, carries every comment of the Block: the page keeps them on the editing engine's node through a drag, and core writes them back at the new place. A split keeps a text comment with the half that holds its quote and a Block comment with the first half; a join keeps all. A removed Block's comments become orphans (`orphan=1`, kept where the Block was, listed under "Text deleted", as deleted text is today); removal is never refused for an open comment.
- **Comment store keys follow the ids.** On every `written` outcome the hub rekeys the Block's comments through the old-to-new id match ADR 0007 already computes. When the source changed outside sheaf (an edit in wp-admin), the hub matches the last tree it saw against the new read with ADR 0007's content fallback; a comment whose Block finds no match becomes an orphan that keeps its last quote.
- **Agents.** `threads` rows (with `block` from decision 08) gain `anchor: "text" | "block"`, `quote` empty for a block anchor. Each row of `blocks` lists the ids of the open comments on that Block. `edit_blocks` may remove a commented Block; its `written` result names the comments the removal orphaned.
- **On the page.** A badge with the count of open comments sits in the Block's gutter beside the drag handle and the add handle, in reading and in editing; a click opens the thread in the comment panel and highlights the Block as a commented text run is highlighted today. The badge is editor chrome (ADR 0008): not in print, the share copy or the PDF.

## Considered options

- **Block-id anchors in the Comment store also for Markdown files.** Rejected: comments would live in two places for one file, a copied file would lose some of them, and a plain Block's content-derived id changes on every edit of that Block.
- **Block comments only on Blocks without text.** Rejected: a remark about a whole table or callout has no natural quote either, and one rule is easier to explain.
- **Removal deletes the Block's comments, or is refused while one is open.** Rejected: deleting loses the discussion silently, and refusing blocks a member or an agent behind someone else's unresolved thread; an orphan keeps both.
- **Re-finding Comment store anchors by quote text instead of ids.** Rejected: a Block comment has no quote, and ADR 0007's match already exists for saves.

## Consequences

- The comment grammar (SPEC 5.2) gains the head field `on=block`, written after `orphan` and in place of `quote`; the parser accepts it, and `find_quote` skips such comments.
- "Commentable" (SPEC 5.1) widens from paragraph, heading, list, quote and table to every Block.
- The Comment store is new hub state, per source and document; the spec fixes its file, its backup with the hub's other state, and how a `threads` call on a remote page reads it.
- The MCP rule that `update` must send back every comment byte for byte holds for `on=block` comments as for text comments.
