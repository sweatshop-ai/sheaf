# Handoff: ticket 187 merged (#637); 187 done

**Date:** 2026-11-23
**Merged:** #637 as 73dd4130; head f1164b71, CI green (run 45258544706; the CA page test was red in run 45242478345 attempt 2 before its fix; attempt 1 lost all four self-hosted runners at once and was rerun).
**Review:** Matt's code-review (Standards: no hard violations; Spec: complete), then boss_review round 1, provisional GO by the Opus fallback (Codex at its usage limit). Codex re-reviews f1164b71 before a deploy.

## What changed

- `src/sheafmd/edit.py` (BZ): `strip_data_attrs` reads each start tag's attributes one at a time (`_ATTR_RE`, quoted values whole) and drops every `data-` one, `data-rd-` included, as `_sanitize` does on the page side. A name straight after a quote or a `/` counts, as html.parser reads it.
- `src/sheafmd/page/live.js` (CA): on a refused shared connection (readyState 2) the leader draws a new `sid` and clears a pending RETRY reopen (`again`, `deferred`).
- `tests/test_edit_data_attr_values.py`: kept values, stripped names and places, and the ticket's list with "the data-sheet" (red on main).
- `tests/page/test_page_shared_live.py`: `test_a_shared_stream_refused_409_is_opened_again_under_a_new_id` (red in CI before the fix).

## Open

- Follow-up box in the ticket: a start tag holding an unpaired quote (`href=a'b`) is never matched by `_START_TAG_RE`, so its `data-` attributes stay on the source side. Present on main before #637 too; reproduction and fix direction are in the ticket.

## Notes

- `gh pr edit --body-file` fails on the Projects-classic GraphQL error; `gh api -X PATCH repos/OWNER/REPO/pulls/N -F body=@FILE` works.
- `boss_review.py --track` cannot import findings from an earlier review; it runs its own round.
