# Markdown with fenced divs as the stored form of blocks

Status: accepted (2026-11-23, block-editor design, decision 04); amended 2026-11-24 (see Amendments below)

A rectoverso that learns richer blocks (callout, columns, button) keeps its recto a Markdown file. A Rich block is a pandoc fenced div carrying its type as a class, its id and its attributes, `::: {#b-intro .callout tone="info"}` … `:::`, read and written with `gfm+fenced_divs`. Raw HTML stays only for a future free-HTML block type and stays locked until the rules for HTML on the front's origin are set. The reason is that the `.md` must stay readable to any agent or system that does not know the editor: with the extension pandoc 3.9 renders the div to `<div id="b-intro" class="callout" data-tone="info">` and writes it back unchanged, and a reader without it still sees every word, only with the `:::` lines as text.

## Considered options

- **Gutenberg-style comment delimiters around HTML** (`<!-- block:callout {json} -->`). Rejected: the body becomes HTML an agent must write correctly, Gutenberg's own rule marks a hand-edited block invalid, and on pandoc 3.9 the delimiter is lost when a changed block goes back from HTML to Markdown.
- **A structured format (JSON or YAML block list, as Editor.js, ProseMirror, Lexical).** Rejected: not readable as a page by an agent or a person, and ProseMirror and Lexical drop or fail on a type they do not know.
- **Markdown with HTML islands** (proposed 2026-11-23). Kept only for the free-HTML type; every type that has a fenced-div form uses it instead.

## Consequences

- sheaf's block splitter, renderer and writer must learn fenced divs (today `gfm` alone shows `:::` as paragraph text).
- Pandoc normalises nested fence lengths (`::::` comes back as `:::::`): a cosmetic change in bytes that the merge and the diff must not report as an edit.
- Plain Markdown blocks keep no stored id; how they get one in memory is the block-model ticket's question.
- Nesting is one level: columns hold columns, which hold plain blocks; a callout holds plain blocks.

## Amendments (2026-11-24)

- **Layout divs as a second level** (decision 06). A `.box` (a plain block carrying only `align` or `pad`) and an `.image` (a resized or aligned image on a line of its own) may sit inside a callout or column. Rich blocks still may not.
- **The button is inline content** (decision 07). It is stored as a bracketed span around one link, `[[Buy](https://example.test)]{.button size="m" variant="primary"}`, read and written with `gfm+fenced_divs+bracketed_spans`, not as a `::: {.button}` div, so it can stand in a table cell, a sentence, a list item, a column or a callout. On pandoc 3.9 it renders to `<span class="button" …><a href>` and round-trips unchanged (`size` is written bare, an HTML attribute, and `variant` as `data-variant`; both sanitisers allow those names); a reader without the extension sees the link with `{.button}` as text. A sized image inside text or a table cell takes the same form, `[![alt](url)]{.image size="50"}`. Pandoc pads table columns on writing, another cosmetic change the merge must ignore.
