# Handoff: buttons instead of ticks on the list (design A), state on 2026-10-30

Ruben's state on sweatshop-ai/sheaf#107 and what remains of #108–#112, for the session that takes over. The spec is `docs/design/2026-10-30-knoppen-op-de-lijst.md` (design A, chosen 2026-10-30, merged in PR #106).

## Where #107 stands

- **PR #113**, branch `t107-list-action-buttons`, head `2bfaa4fa44a11470b9e50bccc5b6d6f7629d67ac`. Worktree `/home/tiroir/Projects/sheaf-wt/ruben`.
- **Gate:** mattpocock code-review (standards + spec) done and fixed; fresh Opus GO rounds: 1bea1ff GO with a P2 (fixed), 6dacf8c NO-GO (fixed), 1b8968a GO, 2bfaa4f GO (only adds `pytestmark = pytest.mark.page`). Three rounds used.
- **CI:** 1b8968a failed because the new page test file lacked the `page` marker and ran in the "not page" step without Chromium (run 41120250971). 2bfaa4f fixes that; its CI was running at handoff.
- **Left to do:** when CI of 2bfaa4f is green, merge (`gh pr merge 113 --merge --match-head-commit 2bfaa4fa44a11470b9e50bccc5b6d6f7629d67ac`), check #107 closed (body says "Fixes #107"), delete the branch. If CI is red, read the failing step before touching code. Codex pass owed after 2026-11-04.
- **P3s left open on purpose:** a click after the reload started is ignored silently; a double-click is press then Undo; after a stale 409 the row's other buttons come back and each gets 409 too; leaving the page in the Undo window drops the press.

## What #107 built

- `src/sheafmd/hub/the_list.py`: every action of a row but Move to is a button (`list-act one-off` or `list-act toggle`; `TOGGLES = {"Share"}`); `aria-pressed` on toggles only. The page script waits 5 s with Undo, locks the row's other buttons, reloads only when every press is answered, keeps refusals per button and says them once after the reload (sessionStorage `sheaf-list-said`).
- Tests: `tests/test_hub_list.py` (`buttons()`, `Button`, `row_press()`); `tests/page/test_page_list.py` drives the hub's list page in Chromium through `context.route`, with Playwright's clock.
- SPEC 9.10 "The buttons on the row (#107)"; GLOSSARY: One-off action, Toggle action.

## What remains: #108 to #112

- **#108** Hub refuses an untick of a one-off (every word but Share), 409, like the Share untick by a non-owner (SPEC 9.11).
- **#109** Move to: one button per candidate on the list; once one is ticked the others stop being actions and a second Move to tick is refused. `POST /_/tick` already ticks any action by index, Move to included.
- **#110** A pressed one-off shows locked with who and when, from the `tick: <path>` commit. Today only unticked boxes are actions (`read_sheaf`), so this needs ticked boxes read too.
- **#111** The same buttons at the top of the sheaf's page.
- **#112** The buttons on a phone (360 px, 44 px targets, no sideways scroll).
