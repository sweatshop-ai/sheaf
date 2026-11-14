# Handoff Tomas, 2026-11-14: ticket 68, PR 296

PR 296, branch chat-box/68, head 7606d99, CI 3/3 green (total_count 3). Two Opus review rounds (Codex was out of tokens): round 1 NO-GO (a/b findings, fixed test-first), round 2 GO. Reviews: /home/tiroir/.claude/pm/chat-box-handoffs/pr-68-reviews/opus-1.md and opus-2.md. Not merged.

## What was done
- 1: tests for `<!-->` and `<!--->` cells (green after ticket 66).
- 2: `_insert_comment` puts the block on its own line after a table (also a quote or list table) when no cell can take it.
- 3: `_mask_code(text, cells=True)` masks code per cell for `table` blocks, in `parse` and `cell_end`.
- 4: `in_table_row` (comments.py) recognises a table in a quote or list, header row included; `add_comment`, `_rewrite` and the merge write one line at the end of the cell. A cell inside a span across cells of such a table is refused.
- 5: limit in SPEC 10.4, with a test against pandoc.

## Ticket 72 overlap
Ticket 68 item 3 covers backticks, escaped or not, paired ACROSS cells and rows (per-cell masking). Ticket 72 point 1 keeps the escaped backtick INSIDE one cell or a paragraph (`CODE_SPAN_RE` prefix). Neither ticket file was edited (they sit on chat-box/next, Cleo's worktree): add one line to each. SPEC limit (3) names 72, which is not on main until chat-box/next merges.

## Follow-up text (no number)
- A tab after a container marker (`>\t| a | b |`, `-\t| a |`): `projection` takes pandoc's sourcepos column with the tab expanded, so the point is 2 characters too far right, and a comment can land after the closing `|` or in the delimiter row, breaking the table. Main breaks more cells there. Fix in `projection` (comments.py ~475).
- Lone backticks in a quoted or listed table are refused as a span across cells although pandoc shows no code (SPEC 10.4 limit 1). A fix: `parse` masks the table rows of a quote or list per cell.
- `in_table_row` says yes to some text pandoc reads as a paragraph (cell count differs from the delimiter row): render unchanged, no harm.
