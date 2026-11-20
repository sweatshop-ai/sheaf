# 168: Rename the List's "Move to <slug>" to "Belongs to <slug>"

**Status:** open

**Blocked by:** none

**From:** wayfinder `sheaf-in-open-webui` ticket 20 (Alice, 2026-11-15)

## Why

The Sheaf gains a **Move** for a rectoverso (into another folder), and AgentView already has "move this session to…" a project. A third "Move to", on the List, for a mail thread's slug, is one move too many. The slug is not always a client (a project, a team), so the word must not say client; "Reassign" clashes with an issue's assignee, who is the sheaf's owner.

## What

- `- [ ] Belongs to <slug> (ref <thread>)` replaces `- [ ] Move to <slug> (ref <thread>)`; the List's button reads "Belongs to <slug>".
- Sheaf: `src/sheafmd/hub/the_list.py` (`WORDS`, `MOVE`), `src/sheafmd/hub/handler.py`, `src/sheafmd/page/page.js` (`ACTION_WORDS`), `page.css`, SPEC 9.10, tests (`test_hub_list.py`, `test_hub_place.py`, `tests/page/test_page_list.py`, `test_page_actions.py`).
- tiroir-mail-replies: `MOVE_TO` in `tiroir_mail_replies/sheaves.py` and its matchers (`ticked_moves`), `cli.py`, tests.
- Transition: the hub and the mail module read both words for as long as an open sheaf still carries "Move to"; the mail module writes only "Belongs to". Ship the readers before the writer.
