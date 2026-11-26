# Blocks take their look from the base stylesheet and theme properties

Status: accepted (2026-11-25, block-editor design, decision 15)

The structure of every Block type (the column grid, alignment, padding, image and column sizes, App height, the button's shape, the callout's frame) is CSS in sheaf's **base stylesheet**, which every page includes before its Theme. The visual look (callout tones, button variants, radii, the S/M/L padding scale) comes from a documented list of **theme properties**, CSS custom properties whose default values also sit in the base stylesheet; a Theme's `theme.css` may override any of them, and may restyle a Block type by its type class. The reason is that `theme.css` replaces plain's stylesheet whole: block CSS kept in plain would leave every existing Theme with blocks that lose their layout, while CSS in the base stylesheet lays blocks out under any Theme, old or new.

## Decisions

- **Sizes without `style`.** `size`, `align` and `pad` reach the screen through attribute selectors on the `data-*` attributes pandoc writes, one rule per allowed step (image 25/50/75/100 %, column split 15 to 85 % in 5 % steps (and the thirds 33 and 67, which the 33/67 and 67/33 presets write; amended 2026-11-26), App height 60 to 800 px in 20 px steps, pad none/S/M/L), generated from the Block type declarations. A value off its steps is refused on write (ADR 0003), so no stored value can lack a rule.
- **Narrow screens and print.** Below 600 px wide, columns stack in source order and their split is ignored; on wider screens, in print and in the PDF they stay side by side at their stored split. An image keeps its share of its column at every width.
- **One look everywhere.** The same block CSS serves the reading view, the edit view, the share copy and the PDF. The **editor chrome** (gutter, add and drag handles, block toolbar, slash menu, selection outline) is sheaf's own stylesheet, apart from it: it takes the Theme's font and accent through properties, and a Theme cannot restyle it.
- **Stubs.** In reading, the share copy and the PDF a Stub's content renders as ordinary content with no frame. In the edit view it gets a dashed frame labelled with its type and a lock.
- **The theme properties are a contract.** Their names are documented and stable through 1.x, like the library API. A new Block type adds properties and never renames old ones. `theme.toml` gains no keys.
- **Themes are trusted admin data.** A Theme is written by the hub's admin only. No member, page or MCP tool writes a Theme's files (a path under a root's `.sheaf/` answers 404), and sheaf runs no CSS sanitiser over `theme.css`. The spec states this.
- **Remote sources.** A Source service never sends styles. A `[sources.<name>]` table in `config.toml` (ADR 0005, 0006) may name a Theme with `theme = …`, as a root's `.sheaf.toml` does; that Theme sits on the owning tiroir and is written by hand to look like the site.

## Considered options

- **Block CSS in plain only.** Rejected: a Theme replaces plain's stylesheet, so every Theme would have to restyle every Block type or show broken columns and sizes.
- **Block look fixed, not themeable.** Rejected: an organisation's pages would carry its fonts and colours around blocks drawn in sheaf's.
- **Block colours and sizes as keys in `theme.toml`.** Rejected: a second way to say what CSS already says, and one sheaf would have to grow with every Block type.
- **Free size values rendered as inline `style`.** Rejected: reopens what ADR 0003 closed.
- **A Source service sends its site's CSS, sanitised and scoped by sheaf.** Rejected for now: a page on the front's origin would carry CSS from outside the hub (remote `url()` fetches, overlays over sheaf's controls), and the sanitiser would be a new attack surface to build and keep. A hand-written Theme gets close enough to the site's look.
- **A sanitiser for `theme.css`.** Rejected: only the hub's admin writes a Theme, the same person who could change sheaf itself.

## Consequences

- The base stylesheet grows by the block rules and the default values of every theme property; `plain`'s look for blocks is those defaults, light and dark.
- The spec lists the theme properties by name with their defaults, in the Theme section.
- `[sources.<name>]` gains an optional `theme` key; without it the source's pages use the hub's default Theme.
- The rule generator for the step selectors reads the Block type declarations, so a new step is one declaration change, never hand-written CSS.
