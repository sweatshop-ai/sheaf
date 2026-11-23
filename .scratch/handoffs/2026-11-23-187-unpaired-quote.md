# Handoff: ticket 187 follow-up merged (#642); 187 done

**Date:** 2026-11-23
**Merged:** #642 as 505b328e; head 11b72450, CI green (ubuntu-24.04 py3.13).
**Review:** boss_review `--track sheaf-backlog`. Round 1, provisional GO by the Opus fallback on a663d1fe (Codex at its usage limit until 2026-11-24 12:39 UTC). Its two minors were fixed in 11b72450. Round 2 was a fix pass (`--since a663d1fe`): GO, no findings. Codex re-reviews 11b72450 before a deploy.

## What changed

- `src/sheafmd/edit.py`: `_START_TAG_RE` reads a start tag attribute by attribute, as html.parser's `locatestarttagend_tolerant` does. A quote opens a quoted value only straight after a name's `=`; names and bare values may hold one. `_ATTR_RE` takes the same names and bare values (`attrfind_tolerant`). The loops are possessive, so a tag that never closes is given up in linear time.
- `tests/test_edit_data_attr_values.py`:
  - quotes inside bare values and names;
  - an `=` inside a bare value;
  - a later tag that was swallowed;
  - parity with BeautifulSoup's attributes;
  - `_unchanged` on a raw HTML block, with a browser-serialised fragment;
  - a linear-time guard (process time, `no_gc`).

## Notes

- The ticket's "boxes refuse the tick" does not happen in a list row: pandoc escapes an inline tag with an unpaired quote. The real case is a raw HTML block, which on main went through pandoc on every save. The correction is in the ticket.
- A regex with two overlapping readings of a quoted value (quoted, or a run of plain characters) backtracks exponentially when the tag never closes. Keep the loops possessive.
- `ruff check src/sheafmd/edit.py` reports two errors that predate this change (F401 at the `NavigableString` import, E731 at the `indent` lambda).

## Open

None on 187.
