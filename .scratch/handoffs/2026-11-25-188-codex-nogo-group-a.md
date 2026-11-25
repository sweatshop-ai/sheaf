# Handoff: ticket 188, Codex NO-GO group A (saving and round-trip of text)

**Date:** 2026-11-25 · **Ticket:** `.scratch/from-render-doc/188-codex-nogo-group-a-text-round-trip.md` · **PR:** #656, merged as e6a5c562 (head 44122abf)

## Outcome per original PR

- **#559:** findings 1 and 2 fixed in #656 (A, B).
- **#555:** finding 2 fixed in #656 (C); findings 1 and 3 already fixed by 9e9d08dc, finding 4 by f1164b71.
- **#494:** findings 1 and 3 fixed in #656 (D, E); finding 2 left open (J: needs an escape for U+E000/U+E001 across hide, show, the emoji read and the comment projection; private-use input).
- **#571:** findings 1, 2 and 3 fixed in #656 (F, G, H).
- **#554:** fixed in #656 (I), except a name with a space (`plan.md (copy).md`), which cannot be told from words in brackets.

## Review and CI

- Review: round 1 through `boss_review.py`, provisional Opus GO, because Codex had hit its usage limit (until 13:06 UTC). The gate accepted it because main is non-deploying. Its three minor findings are listed in the ticket and left open.
- CI: run 45583371071 failed on the runner's DNS (wheel smoke step could not reach pypi.org). Run 45595912589 failed when the runner lost its connection mid-test; its rerun was green.

## Observations outside the ticket

- With Enter before a heading's comment anchor, the anchor moves down to the new paragraph and a `\` hard break is written before it. Seen in CI run 45575794890; the cause is not established. The page test asserts only the heading and the paragraph under it.
