# 168: Rename the List's "Move to <slug>" to "Belongs to <slug>"

**Claimed by:** Karim 2026-11-20 15:56

**Status:** in review. Sheaf PR #480 has review round 1 GO on b775d08f; its CI waits on a re-run of slices 2 and 4 (a hang, see below). The mail-replies PR is held.

**Blocked by:** none

**From:** wayfinder `sheaf-in-open-webui` ticket 20 (Alice, 2026-11-15)

## Why

The Sheaf gains a **Move** for a rectoverso (into another folder), and AgentView already has "move this session to…" a project. A third "Move to", on the List, for a mail thread's slug, is one move too many. The slug is not always a client (a project, a team), so the word must not say client; "Reassign" clashes with an issue's assignee, who is the sheaf's owner.

## What

- `- [ ] Belongs to <slug> (ref <thread>)` replaces `- [ ] Move to <slug> (ref <thread>)`; the List's button reads "Belongs to <slug>".
- Sheaf: `src/sheafmd/hub/the_list.py` (`WORDS`, `MOVE`), `src/sheafmd/hub/handler.py`, `src/sheafmd/page/page.js` (`ACTION_WORDS`), `page.css`, SPEC 9.10, tests (`test_hub_list.py`, `test_hub_place.py`, `tests/page/test_page_list.py`, `test_page_actions.py`).
- The mail-replies repo (private): `MOVE_TO` in `tiroir_mail_replies/sheaves.py` and its matchers (`ticked_moves`), `cli.py`, tests.
- Transition: the hub and the mail module read both words for as long as an open sheaf still carries "Move to"; the mail module writes only "Belongs to". Ship the readers before the writer.

## Condition on the mail module

Do not merge the mail-replies PR before a sheaf release with #480 runs on the hub that reads the mail sheaves. Merging is no deploy, but pulling main onto the box would be one: until the hub reads "Belongs to", every open unsure thread loses its client chips and the one-client guard stops firing.

## Known transition behaviour

A page line that still reads `- [ ] Move to <slug> (ref <thread>)` shows its own words as the button on the page, not "Belongs to", until the mail module rewrites the sheaf. The List already reads it as "Belongs to".

## Done

- [x] Sheaf side written and tested: hub list and place tests passed (354 first run; 32 on the refusal-text subset), `test_page_assets` 21 passed; on t-compute all of `tests/page` passed (1076, with `-n 6`). PR #480, review round 1 GO on b775d08f.
- [ ] #480 CI green: slices 2 and 4 of run 44765451025 are to be re-run (slice 2 failed on the `test_mount_sheaf` flake that main also has; slice 4 hung in the page-test step). Then merge.
- [ ] Mail-replies side: written and reviewed (full suite on t-compute 6819 passed, same as main's 6818 plus the new test; no failure that main lacks), held unmerged for the condition above.
