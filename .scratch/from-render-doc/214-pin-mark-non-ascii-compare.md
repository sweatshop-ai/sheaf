# 214: a pin time with a non-ASCII mark raises instead of reading as not believed

**Claimed by:** Kenji

**Status:** done (branch kenji/214-pin-mark)

**Blocked by:** none

**From:** the Codex check on PR #701 (ticket 213), after its merge. [P2], no NO-GO.

**Where:** `src/sheafmd/hub/state.py`, `Versions._pinned_at`.

## Finding

- [x] **A.** (P2, state.py:339) `hmac.compare_digest(mark, self._mark())` compares two `str`, and raises `TypeError` when one holds a non-ASCII character. A `.at` in a root's own store reading `<ns> é` (corrupted, or carried by git) makes reading or trimming that document's pins raise instead of returning 0, a pin not believed. Verified: `hmac.compare_digest('é', 'ab')` raises `TypeError: comparing strings with non-ASCII characters is not supported`. Fix: compare bytes (`mark.encode("utf-8", "surrogateescape")` against the mark's bytes), or refuse a mark that is not 32 hex first. Red test first: a `.at` with a non-ASCII mark is read as 0 and the pin is neither believed nor counted.

## Notes

- Not reachable from what a hub writes: every hub before #701 wrote a bare number, and #701 writes 32 hex. Only a hand-made or corrupted file triggers it.

## Evidence

- `_pinned_at` refuses a mark that is not exactly 32 lowercase hex (`state._MARK`), then compares bytes with `hmac.compare_digest`; anything else reads as 0, a pin not believed, and raises nothing.
- Test: `tests/test_hub_state.py::test_a_pin_time_whose_mark_is_not_32_hex_is_not_believed` (non-ASCII, a lone surrogate, non-hex, 33 hex), the two non-ASCII cases red on main with `TypeError`.
- Review: one recorded boss_review round; no further Codex pass (decided for this track).
