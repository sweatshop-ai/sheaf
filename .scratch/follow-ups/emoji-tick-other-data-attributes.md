# A box in a list with raw HTML carrying a `data-*` attribute still refuses every tick

**What to build:** Review of PR #473 (Opus fallback, Codex out of tokens) found one minor case. `edit.py` reduces only `data-emoji` on a `<span>` in the source render (`EMOJI_ATTR_RE`), while `_sanitize` strips every `data-*` attribute from the page fragment. A list that holds raw HTML such as `- [ ] <span data-x="1">a</span>` keeps `data-x` on the source side only, so the two never compare equal: every box in that list is refused, and the block counts as edited on every save. Strip every `data-` attribute that is not `data-rd-*` from the source render, as `_sanitize` does the fragment, and pin it with a test.

**Blocked by:** None.

**Status:** open

- [ ] A list with a raw `<span data-x>` item ticks a box, tested red first
