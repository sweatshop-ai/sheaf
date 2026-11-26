# 210: Codex NO-GO group P (edit.py hard-break runs and escaped shortcodes in word pairs)

**Claimed by:** Imani

**Status:** in progress (2026-11-26)

**Blocked by:** none

**From:** Codex recheck pass 7: #685 round 06 and #691 round 02.

**Where:** `src/sheafmd/edit.py`, the pairing of hard-break runs and `_word_pairs`.

## Serious

- [ ] **A** (#685 round 06): summing similarities lets a new run with partial matches on both sides outrank the source run with one unchanged line beside it. Source `Alpha one two three\` / `` / `Beta four five six` against page runs `Alpha one two three<br><br>Alpha one two<br><br>Beta four five`: the source run is split into paragraphs and the newly inserted run is kept as hard breaks, the reverse of the edit. Red test first.
- [ ] **B** (#691 round 02): `_word_pairs` can return a partial match that omits an escaped shortcode, so `_places_by_order` skips its unique-neighbour fallback. Moving `A \:smile:` across two long repeated-word stretches while adding another `:smile:`: the escape is lost. Red test first.
