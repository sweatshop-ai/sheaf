# Blocks cross a whole-document source adapter as a tree

Status: accepted (2026-11-24, block-editor design, decision 07)

The block editor reaches its source only through a **source adapter**, and the adapter knows nothing of block operations. It offers `read() → (blocks, base)` and `write(blocks, base, author, note) → outcome` on one whole document, where `base` is an opaque string the adapter alone interprets (today a content hash, a git blob sha for a file in a repo, a `modified` time for a CMS post). Inserting, moving, removing and editing one block happen in sheaf's core on the block list, which then writes the whole document. The reason is that the sources this must fit write whole documents and store no block id: a Markdown file, an Astro site's content files (one file per commit, the file's sha as base) and a WordPress post (`content.raw` as one string, no conflict check of its own). An interface with per-block operations would be faked by every adapter.

## The block list

The block list is a **tree**. Each block has an id, a Block type, its declared attributes, its content and its capabilities; a Container holds child blocks.

- **Containers:** columns (holding columns), column and callout, plus Markdown's own quote and list item. Quote and list item hold plain blocks only; a Rich block inside them is refused. A callout or column may hold plain blocks and layout divs (`.box`, `.image`), never another Rich block (ADR 0001, as amended).
- **Inline content is not a block.** Text, links, an image inside text or a table cell, and a button are content of the block that holds them: they have no id and move with it. A table cell holds inline content only.
- **Ids.** A Rich block or layout div uses its stored `#id`. A plain block gets an id in memory, derived from its content (a short hash of type and text, suffixed when two blocks are equal), so an edit elsewhere in the document leaves it valid; it changes once its own block is edited. An adapter that has an id of its own for a block (a field path, a block attribute) supplies it, and that id wins.
- **Capabilities.** Per block the adapter declares `edit`, `move` and `remove`; per document and per container, the Block types that may be inserted. The Markdown-file adapter allows everything except on a Stub or locked raw HTML, which can be moved and removed only.

## Outcomes of a write

A write ends in exactly one of three outcomes, reported alike to the page and to an agent:

- **written**: the new base and the new ids.
- **conflict**: the base is stale and a block the write targets has changed or gone since that base; the current content of those blocks comes back. When the base is stale but every targeted block is unchanged, core applies the operations to the current version instead. On the page a conflict becomes the existing block merge with conflict comments; an agent re-reads.
- **refused**: a reason and the block it concerns: a type that is not declared, an attribute against its declaration (ADR 0002), a missing capability, or the source refused or filtered the write. A refusal is never reported as a conflict.

## Saving, publishing and comments

- Every `write` carries an author and a note; the adapter decides what it becomes (a version entry, a revision). A source where a write is a public change declares an optional `publish(note)` and keeps writes as a draft until then.
- Comments are outside the interface. The Markdown-file adapter keeps its inline HTML comments as private storage; any other adapter's comments go to a hub-side store keyed by document and block id.

## The first adapter

The Markdown-file adapter is built from what exists: the plain-text file write, the live document and the versions store. Markdown with fenced divs and bracketed spans (ADR 0001) is both its stored form and the wire form between core and the page, where the editing engine (ADR 0003) reads and writes it. The checks that a path ends in `.md` stay until a second adapter exists.

## Considered options

- **Per-block operations on the adapter** (insert, move, delete one block). Rejected: neither a content-file source nor WordPress can do them natively, so each adapter would rebuild the document itself, differently.
- **Markdown text across the interface.** Rejected: an adapter over YAML fields or a CMS's block grammar would have to invent Markdown for content that has none, and capabilities and ids would have nowhere to live.
- **Plain block ids by position within one base.** Rejected: any edit above a block makes an agent's id stale, so a member typing anywhere would turn every agent edit into a conflict.

## Checked on paper

- **Astro content files.** A block is a field of a YAML file (path plus dotted field path as its id). Capabilities: `edit` on text fields, no insert, move or remove (the file's shape is fixed). Base: the file's blob sha; two edits to different fields of one file conflict at the source, which core's rebase rule turns back into a write when the fields differ. Writes on staging are drafts; `publish` promotes them. HTML and comments cannot be stored, so comments use the hub store.
- **WordPress.** `parse_blocks` gives the tree; the id is a `metadata` attribute when present, else derived from content. Static blocks whose markup the server cannot regenerate are not `edit`. Base: the post's `modified` time, compared after a fresh read just before writing (not atomic, the source has no check). Each write is a revision; HTML filtered on save is reported as a refusal after reading back what was stored.

## Consequences

- sheaf's index-based blocks (`<!--MDB:i-->`, `{i, html}` saves) give way to the block tree with ids; the page sends whole Markdown and core finds the changed blocks (with the ids the page holds, ADR 0007).
- The merge must treat pandoc's cosmetic normalisation (fence lengths, table column padding) as no change.
- The MCP tools over blocks (a later decision) speak this block list, its ids and its three outcomes.
