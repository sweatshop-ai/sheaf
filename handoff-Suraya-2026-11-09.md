# Handoff from Suraya, 2026-11-09: ticket 01 (chat-box/01), stopped at the boundary

Branch `chat-box/01`, worktree `/home/tiroir/Projects/sheaf-wt/chat-box-01`, cut from `cleo/chat-box`. Not merged back, no CI run started (Isolde, 17:20). The ticket file `/home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/issues/01-le-fil-en-boite-de-chat.md` is not ticked and stays `in-progress`.

## Run proof (own copy)

- `uv run python -c "import sheafmd; print(sheafmd.__file__)"` printed `/home/tiroir/Projects/sheaf-wt/chat-box-01/src/sheafmd/__init__.py` (own `.venv`, created by `uv run` in this worktree; `command -v uv` = `/home/tiroir/.local/bin/uv`).
- Tests start their own hub on a port of their own under their own `SHEAF_HOME` (tests/page/conftest.py), never 27419 or 27519. Basetemps `/tmp/pt-suraya` and `/tmp/pt-suraya2`.
- Last runs: `tests/page/test_page_chat_box.py` + `test_page_waiting_tell.py` + `test_page_outage.py`: 82 passed, 1 failed (`test_an_empty_box_does_not_hold_a_reload_but_typed_text_does`, then made deterministic and run alone: 1 passed). Log `/tmp/claude-1000/-home-tiroir-Projects-sheaf-wt-chat-box-01/47d4634c-0f28-4405-b43c-1b9c34074ffe/scratchpad/final1.log`.

## Decisions made with Isolde

- **Decision A**: the page's own controls are not "a click beside" the box. The click-outside exclusion list in `page.js` (mousedown handler of the popover) now holds `.rd-badge, #rd-panel, #rd-unsent, #rd-actions, #rd-notice, #rd-menu-btn, #rd-menu, #rd-mode, #rd-work`. The box stays and typed text holds the reload; old tests keep their meaning. Guards: `test_a_click_on_the_document_minimizes_the_box_and_keeps_the_text` (green) and `test_a_click_on_a_page_control_is_not_a_click_beside_the_box` (red without the exclusion, green with it, proven).
- **Mode switch (`#rd-mode`) is ticket 02's ground too**: it is excluded here; ticket 02 starts from that.
- **0.016 px**: `test_the_form_goes_back_to_its_place_when_the_keyboard_closes`. Measured popover rects over 6 keyboard open/close cycles: start `[16, 726.40625, 356, 908.484375]`, after the first cycle and every later one `[16, 726.390625, 356, 908.46875]` (one drop of exactly 1/64 px, no growth). Old assertion: `rects(page)["pop"] == before`. New: `== pytest.approx(before, abs=1 / 64 + 1e-6)` with a comment saying why.

## Changes in this branch

Code (`src/sheafmd/page/page.js`): the not-sent line names a new comment put away unsent "message(s)" (`MESSAGE` kind, `kindOf`; red then green on `test_a_minimized_new_message_is_named_a_message_in_the_not_sent_line`); the click-beside exclusion list (decision A). `SPEC.md`: new "The thread is a chat box" block and table in 10.4, 10.4 "Writing", "Escape and a click outside", "A send is per form" and the not-sent line text, 10.2 Escape sentence.

Other ticket-01 code gaps were already in the code and are covered by new tests that passed on first run (no code change): × and ⋯ on a resolved thread (bandHtml), the thread opening on its last message (existing test), a reload held only by typed text, IME `isComposing` (page.js textForm keydown).

Tests added in `tests/page/test_page_chat_box.py`: not-sent message line; resolved thread × closes / Reopen in ⋯ / Edit and Delete for own; resolved thread of another person has only Reopen; empty box does not hold a reload but typed text does; IME Enter does not send; legacy kept reply (store written by the older page, `thread`/`kind: reply`, no `min`) is listed "1 reply not sent" and comes back in its thread; the two decision-A guards. Not proven red (they passed on the existing code): IME, legacy, held reload, resolved thread. Say so in the report.

### Assertions removed or restated so far

- `tests/page/pagehelp.py` `comment_on`: was select, click `#rd-comment-btn`, fill, click `data-f=ok`. Now select, wait for the textarea or the Comment button, click the button only when the box did not open itself (touch), fill, click `data-f=ok` or `data-f=tell`.
- Mechanical, same meaning: "click `button[data-a=reply]`" became "wait for `#rd-popover textarea`" (the field is open from the start), and "wait for the Reply button" became "wait for the textarea", in `test_page_waiting_tell.py` (4), `test_page_agent.py` (3), `test_page_outage.py` (2), `test_page_drafts.py` (3), `test_page_keyboard.py` (2), `test_page_actions.py` (1) and `test_page_writing.py` (about 80 sites, by regex). Five assertions in `test_page_writing.py` still look for `button[data-a=reply]` ("the thread's buttons did not come back", lines about 2388, 2554, 2604, 3336, 4143): not touched yet.
- `test_page_agent.py::test_a_thread_and_its_reply_form_say_why_their_tell_button_cannot_work`: removed the assertions that the thread's own `.rd-actions` row holds a disabled Tell button with the hub's line (that row has no Tell any more); restated as "no Tell and no Ask in the thread's own actions" plus the unchanged form assertions.
- `test_page_keyboard.py`: the 1/64 px comparison above.
- Duplicate wait lines left by the regex in actions and keyboard were removed.

## test_page_writing.py: first results, and what is not known

216 `def test`, 307 with parameters. The run was stopped at 91 results (58 F, 18 E, 15 pass) because of load 16 to 18 (other sessions) and 20 s timeouts. The log has no failure details (pytest prints them at the end; the process was killed): `/tmp/claude-1000/-home-tiroir-Projects-sheaf-wt-chat-box-01/47d4634c-0f28-4405-b43c-1b9c34074ffe/scratchpad/f-writing-partial.log` holds only the progress dots. Result per test, in order, with static tags from each test's body: `.../scratchpad/classified.txt` (`index result name tags`), collection order in `.../scratchpad/collected.txt`.

Clusters of those 91 (tags are from reading the body, not from the failure message):

| Cluster | F | E | pass |
|---|---|---|---|
| Cancel `data-f=no` on a reply form | 12 | 3 | 1 |
| Cancel and `#rd-comment-btn` (ticket 02 too) | 2 | | |
| `#rd-comment-btn` only (ticket 02) | 6 | | |
| "Send or cancel first" | | 1 | |
| no tag: not classified (38 F, 14 E, 14 pass) | 38 | 14 | 14 |

The 14 E are fixture errors at setup (not yet looked at: probably `kept` / `two_threads` fixtures that wait on the Reply button or on `#rd-comment-btn`). The 38 untagged F are mostly tests using the `thread` fixture and `open_reply`; their cause is not established. Test names not yet classified: every line of `classified.txt` with an empty fourth column and result F or E, plus all tests after index 91.

## Ticket 02 group (select, then click `#rd-comment-btn`; left alone)

All fail with "waiting for locator #rd-comment-btn" or the helper's old wait, because a mouse selection now opens the box. List (44, from the logs `r1.log`, `f-actions.log`, `f-drafts.log`, `f-keyboard.log`, `f-work.log` and Cleo's `suite1.log`): file `.../scratchpad/t02u.txt`. After the click-beside change, expect some of them to need the Decision-A behaviour as well once their button click is replaced by a wait for the field. The same pattern is in `test_page_writing.py` (about 8 tests tagged `t02-comment-btn`).

## Ticket 01 boxes: what is proven

1. Old form tests describe the new contract: partial. Proven: waiting_tell (3/3 pass), outage (57 pass in the first run), agent except ticket 02 ones, keyboard except 1 ticket 02, actions 182 and drafts 165/417 (3 passed together after decision A: `uv run pytest ... -k "reloads_the_page_waits_for_a_press or restored_while_a_reply or save_failed_while_a_draft_is_offered_is_kept_once_the_draft_is_restored"` gave 3 passed). Not proven: `test_page_writing.py` (cluster work below), `test_page_list.py` (never run by anyone), the rest of the actions/drafts file after decision A (last full runs predate it: actions 6 failed / 34 passed, drafts 3 failed / 22 passed, the failures being ticket 02 ones plus the three above).
2. Reload held only by typed text: proven by `test_an_empty_box_does_not_hold_a_reload_but_typed_text_does` (passes).
3. Not-sent line names a message: proven, red then green.
4. Resolved thread × / ⋯: proven by two new tests (pass), no code change needed.
5. Thread opens on its last message: existing `test_a_long_thread_opens_on_its_last_message_and_scrolls_up` passes (chat_box file, 82 passed run).
6. Spec: written (SPEC.md 10.2, 10.4); needs a read by someone else.

Isolde's three additions: (1) no assertion deleted to get green: the removals are listed above; (2) legacy draft test added; (3) IME test added.

## Plan for the next session

1. Read `classified.txt`. Run the untagged F and E tests of the first 91 in small groups with `--tb=short` to learn the cause (start with the 14 setup errors: one fixture each).
2. Fix the known clusters first: Cancel on reply forms (a reply form has no Cancel: restate with Minimize, or Discard in the not-sent list, test by test, keeping what each test checks); "the thread's buttons come back" (5 sites); "Send or cancel first" (gone; assert instead that the badge opens another thread and the typed text is kept).
3. Rerun only those tests, one cluster at a time. Check `uptime` first (above 8 wait). Kill your own runs by pid; never `pgrep -f` or `pkill -f` with a pattern that is in your own command line (it killed this session's shell once).
4. Run `test_page_list.py` once.
5. Then one whole-file run of `test_page_writing.py` at the end (about 70 minutes under load 16; log with `--tb=short -rf`).
6. Push `chat-box/01`, start `gh workflow run ci.yml --ref chat-box/01 -f python=3.13` only on the head you deliver (read `ci.yml` first to confirm a manual run includes the page tests; not done yet), check `.total_count` first. Tick the ticket boxes with evidence, merge into `cleo/chat-box` from `/home/tiroir/Projects/sheaf-wt/cleo-chat-box`, push it.
