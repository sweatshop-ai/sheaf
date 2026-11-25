# Handoff: ticket 199, render time limit regressions (2026-11-25)

**Status:** claimed (0e48640b). The rules and design are in the ticket; no code yet. Handed off at claim because the session that wrote it was near its context limit.

## Start here

1. Read the ticket: `.scratch/from-render-doc/199-render-budget-regressions.md`.
2. Read the background: ticket 198 boxes D, F, G and H, plus PR #669 (merged as 24e74512).
3. Work on branch `<name>/199-...` in a /tmp worktree. Write a failing test first for each of G and H.
4. Run locally only the touched files: `tests/test_hub_index.py` (or its `-k "pandoc or render"` subset), `tests/test_pandoc.py`, and the CLI test file for `sheaf open`. Command: `PYTHONPATH=src /home/tiroir/Projects/sheaf/.venv/bin/python -m pytest -q <file>`.
5. Do one review round, then merge through `boss_merge.py --repo sweatshop-ai/sheaf --pr N`. The gate needs a round recorded by `boss_review.py --repo sweatshop-ai/sheaf --pr N --checkout <worktree> --author <name> --track sheaf-backlog`. That runs the Opus fallback while Codex is out (account b, until 2026-11-26 00:42).

## Points to know

- `place.held` is bound to the thread that holds it, so the worker thread in `Hub.render` must take it itself.
- `/_/render` is called only by `sheaf open` (`cli.py`, about line 342) through `handler.py`, about line 2803.
- Keep 198 F: in `comments.py`, `_read_tables` does not cache a failed reading.
- The 198 D test in `tests/test_hub_index.py` patches `_pandoc._clock`. It goes away together with the budget.

## Open decision

The track asked that "the 120 s budget starts only after the locks are taken". The design meets that by removing the shared budget, so that no pandoc run is ever cut by a lock wait. The hub's answer limit to the client must still count the lock wait, because the client's 130 s includes it. The track has been told.
