# Handoff: diagram viewer for SVGs and mermaid diagrams (2026-11-26)

**Status:** done. Merged in #678 as 4c601097. SPEC 6.9, CHANGELOG line under Unreleased "Added".

## What landed

- Click or tap on an inline SVG (mermaid, chart) or an `img` of an SVG opens a full-window viewer (`#rd-zoom`, `src/sheafmd/page/page.js`, `page.css`).
- Wheel and pinch zoom about the pointer, drag to pan, Fit button or double-click to reset, `+`/`-`/`0`/arrows; closes by Esc, the close button or a click outside. Works in light and dark, on a phone, and in Edit mode (no DOM mutation, so saves are unaffected).
- The `--share` copy has no viewer, by decision: it must stay script-free (SPEC 6.1).
- Tests: `tests/page/test_page_svg_zoom.py`, 8 tests.

## Evidence

- Page tests ran on t-compute over ssh (not in CI: the Tests step failed on `test_land_root` first, so the page steps were skipped in run 45718830657). `test_page_svg_zoom.py`: 8 passed. Whole `tests/page`, Chromium: 1158 passed, 0 failed.
- Firefox and WebKit cannot be installed on t-compute (Playwright does not support ubuntu26.04); those variants were not run for the other page tests.
- `test_enter_at_the_end_of_a_task_item_then_a_comment_on_the_new_words_deleted_keeps_the_comment_and_throws_nothing` is flaky: 1 failure in 15 runs on the merge-base and 1 in 15 on this branch.
- Review: Matt's code-review once; boss_review round 1 was the Opus fallback only (Codex gave no answer): provisional GO.

## Open

- No pinch, double-tap or light-theme test; the dark-theme assertion is weak.
- Mounted (shadow-root) mode is untested: focus restore, `zoomGround` stops at the shadow boundary.
- No pan limit; ids are duplicated in the cloned SVG; `openZoom` is long with magic numbers; SVG images inside links show the zoom-in cursor.
- Option for later: a CSS-only lightbox for the share copy.
