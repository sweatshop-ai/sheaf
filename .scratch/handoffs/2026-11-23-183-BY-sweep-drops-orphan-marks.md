# Handoff: ticket 183 BY merged (#635); 183 done

**Date:** 2026-11-23
**Merged:** #635 as 535124db; head a24cfcc2, CI green (ubuntu-24.04 py3.13).
**Review:** Matt's code-review (NO-GO on a Move race, fixed), then boss_review rounds 1–3, all provisional GO by the fallback reviewer (Codex at its usage limit). Codex re-reviews a24cfcc2 before a deploy.

## What changed

- `src/sheafmd/hub/archive.py`: the archive sweep drops the archived, seen and keep marks of an address that holds no page. An address must fail two looks (not in the listing, and nothing but a folder there) at two sweeps running; a failed `stat` counts as a page. The sweep reads and writes the marks under `moves.exclusive()` then `loose-keep.lock`, so a Move of the same process is never half seen. A sweep that does not read a root (refused or skipped) starts that root's run over. `_unmark` takes several addresses and tries every clear before raising; the sweep uses the quiet form, so an unwritable mark file leaves the marks for the next sweep and still archives the root's other pages.
- `src/sheafmd/hub/lockorder.py`: the moves line names the sweep.
- `SPEC.md` 8.6: the rule above, including that the moves' lock is per process (a Move in another hub process is covered by the two sweeps alone).
- `tests/test_trash.py`: nine tests, each red on the head before its fix.

## Residual (note under BY, no letter)

A page made at an emptied address before the second sweep that finds it empty (at most twenty minutes) still inherits its keep and seen marks; nothing drops them on a create or an editor save.

## Ticket 183

Status set to done. The Status line lists every merged head that Codex still re-reviews.
