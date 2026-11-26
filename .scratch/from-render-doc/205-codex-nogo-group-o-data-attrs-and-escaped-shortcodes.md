# 205: Codex NO-GO findings on merged PR #670 (group O, edit.py data attributes and escaped shortcodes)

**Claimed by:** Alonso

**Status:** claimed

**Blocked by:** none

**From:** the Codex re-check of #670 (ticket 197's fix), round 02, NO-GO. Two findings, both marked serious.

**Where:** `src/sheafmd/edit.py`: `_strip_tag_data` / `strip_data_attrs` (a `data-` attribute right after a `/`), `_in_its_gap` (which `:name:` of a changed stretch an escaped shortcode takes).

## Serious

- [ ] **A** (`strip_data_attrs`): `strip_data_attrs("<div/data-x>")` returns `<div/>`, a tag that closes itself, where the parser reads a `<div>` that stays open with a `data-x` attribute; raw HTML nobody touched can then compare as changed and be rewritten.
- [ ] **B** (`_in_its_gap`): a `:name:` chosen for one escaped shortcode is not reserved, so two escaped shortcodes of a long changed stretch can take the same one; the other then shows as its emoji.
