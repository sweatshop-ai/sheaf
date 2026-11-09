# Handoff from Cleo, 2026-11-09: state of the chat box work

The plan and tickets say what to build. This note holds only what they do not: the state of the code and the traps already met.

## State of the branch

- Branch `cleo/chat-box`, head 827a7c4, pushed to `origin` (`sweatshop-ai/sheaf`). No PR yet, so no CI has run.
- The code of tickets 01 and 02 is written. `tests/page/test_page_chat_box.py` passes (15 tests).
- The older page tests are not adapted. A local run of every page file except `test_page_writing.py`, `test_page_chat_box.py` and the list tests was at 8 failures in its last third and dozens before it. No complete result exists, and `test_page_writing.py` has not been run on this code at all.

## Contract changes the older tests must follow

- The reply form is open from the start: the `button[data-a=reply]` field is gone. Wait on `#rd-popover textarea`; do not click Reply.
- An empty open form is not "writing": it no longer holds a reload.
- Text typed no longer blocks closing or opening another thread: `closePopover` keeps it in the store (`f.stash`). "Send or cancel ... first" is gone.
- `data-f=no` (Cancel) exists only on the Edit form. Kept-text lists still have Discard.
- On desktop in Comment mode a selection opens the box: `#rd-comment-btn` stays only for a refused selection and on touch.
- With an agent the only send is `data-f=tell`; without one, `data-f=ok`.
- The Close control on an open thread is `button[data-a=status]`; Edit and Delete are inside `.rd-more`, which must be opened first.

## Known gaps in the code

- A minimized new comment is counted as "reply" in the not-sent line (ticket 01).
- The touch bar has never been looked at (ticket 03).
- Ctrl+C is tested with a simulated copy event only (ticket 02).

## The demo page Thierry tries

A separate hub on port 27519, its state under this session's scratchpad, serves `essai-boite-de-chat.md`, so his real hub on 27419 is untouched. It reads the page's scripts once at start: restart it to show new code. Its command line is in `/tmp/claude-1000/-home-tiroir-Projects-render-doc/c5908d5a-7f9d-42e5-ba54-4f15c4fec36d/scratchpad/demo/env.sh` (`sh env.sh stop`). To open a page signed in, run `sheaf open` with the real `HOME` and `DISPLAY` and without `SHEAF_NO_BROWSER`; never run `sheaf signin-url`. A fake agent `demo-agent` is registered: Thierry picks it under Change in the page's menu.

## Traps met in this session

- `pkill -f <pattern>` killed the session's own shell when the pattern was in its command line.
- A foreground Playwright run that waits on a missing selector takes 30 s per test: prove red on one test at a time.
- A `timeout` under the real duration of the suite gave no result at all (560 s was too short): log to a file.
