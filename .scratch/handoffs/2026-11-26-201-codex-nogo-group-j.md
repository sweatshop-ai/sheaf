# Handoff: ticket 201, Codex NO-GO group J (edit.py break runs and heading remnants), 2026-11-26

**Claimed by:** Alonso. **State:** done, merged in #685 (0d0e3541).

## Result per original PR

- #656, finding 1 (a run of the source's hard breaks recognised only by one unchanged line beside it): fixed in #685 (201 A). Runs are paired in order with the source's, most pairs first, then most words kept beside them.
- #656, finding 2 (`remnant` deleted an empty link target in a split heading): fixed in #685 (201 B).

## Review

Matt's code review, then Codex b. Codex b gave no verdict on three rounds, so the Opus fallback reviewed (GO, provisional, rounds 01 to 03), each later round on the fix diff only. Codex's own recheck (round 04) gave NO-GO: the pairing counted words before pairs. Fixed test first in 84bfbe62; fallback GO on that diff (round 05). Merged through `boss_merge`.

CI on the merged head: 11327 passed, one failure, `test_land_root`, which fails on main too until #677 lands. An earlier run on the branch lost its runner mid-run; another failed `test_archive` once, which passes locally and on main's runs (edit.py is not in its path).

## Open

- 201 A2 (minor): a new run of the source run's length sharing one word with a line beside it is paired with it once the source's own run is gone, and saved as hard breaks instead of two paragraphs. No text is lost; left open in the ticket with the reason.

## Next

Group O of pass 6 (#670, ticket 197's fix, edit.py: `strip_data_attrs("<div/data-x>")` and `_in_its_gap` not reserving a candidate), same worker.
