# TipTap is the block editing engine, inside sheaf's own page

Status: accepted (2026-11-24, block-editor design, decision 11)

Editing a rectoverso block by block needs rich text inside a block, selection, undo, a drag handle, alignment and image resizing. sheaf does not write that machinery itself: it runs TipTap (all `@tiptap/*` packages used are MIT) inside its existing vanilla `page.js`, with no UI framework. The stored form stays Markdown with pandoc fenced divs (ADR 0001): sheaf writes its own reader and writer between that Markdown and TipTap's document, in the per-node `parseMarkdown`/`renderMarkdown` hooks, with pandoc's exact spelling and only declared attributes (ADR 0002). sheaf builds what TipTap leaves open: the slash menu and block toolbar, the column, callout, button and Stub nodes, column widths and padding. TipTap's own Markdown container syntax (`:::name {attrs}`) is not used, because pandoc does not read it.

## Considered options

- **Plate (MIT, React).** The most complete open-source match: columns with `%` widths, alignment, resize, drag and drop, slash menu. Rejected: the editor would be a React island beside sheaf's comments, Tells, live reload and save, which would have to cross the React boundary, and its shadcn look would be restyled to sheaf's themes.
- **BlockNote (MPL-2.0 core, React UI).** The most Gutenberg-like interaction out of the box. Rejected: React plus 253 kB of UI, columns only in the GPL-3.0-or-proprietary `xl-multi-column`, an unknown block type throws, and its Markdown export is lossy.
- **Gutenberg's `@wordpress/block-editor`.** GPL-2.0-or-later, React, 972 kB. Kept only as the reference model for how alignment and spacing are offered and stored.
- **sheaf's own code, as in the ticket 06 prototype.** Rejected by the owner: rebuilding rich text, selection and undo when an open-source engine does it.

## Consequences

- sheaf gains its first JavaScript dependency and a build step or a vendored bundle (about 136 kB min+gzip: starter kit, markdown, drag handle). How it is built and pinned is decided when it is implemented.
- Every block type sheaf declares is also a TipTap node; an unknown fenced div is mapped to the Stub node before TipTap loads, because ProseMirror drops or rejects nodes it does not know.
- Layout settings (alignment, padding, sizes) are stored as declared attributes on the fenced div and rendered as classes, never `style`. Attribute names `width` and `height` are not used, because pandoc 3.9 turns them into `style`.
