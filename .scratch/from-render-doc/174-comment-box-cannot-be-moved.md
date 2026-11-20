# 174: The comment box cannot be moved


**Claimed by:** Zeynep 2026-11-20 18:32

**Status:** done (PR 501, merged as 8c4fe495; follow-ups in .scratch/follow-ups/comment-box-drag-gaps.md)

**Blocked by:** none

**From:** asked by the owner, 2026-11-20

**Where (main bb3eafb8):** `src/sheafmd/page/page.js` (`place`, `replace`, `pin`, `dock`/`undock`, `bandHtml`), `src/sheafmd/page/page.css:69` (`#rd-popover`) and `:127-131` (`.rd-head`), `SPEC.md:1262`

**Size:** one decision on touch screens, then a drag handler, its CSS and tests

An open comment box can cover the text the owner wants to read. They want to grab the box by its top band and drag it elsewhere.

## To do

- [x] Decision (the boss, 2026-11-20): the box is draggable everywhere except while it is docked to the keyboard (`dock()`: a touch screen with the keyboard up). While docked the band shows no move cursor and a drag does nothing. `undock()` brings back the place the box was dragged to. Reason: `replace()` re-applies the docked position on every `visualViewport` resize or scroll, so a drag would snap back, and overriding the dock fights the keyboard handling on iOS. `touch-action: none` goes on the band only, never on the passage text, so the page still scrolls under a finger that starts elsewhere.
- [x] Drag the box by its band with pointer events, so mouse and touch both work. A press on a band button (Resolve, Close, the ⋯ menu) or on a link in the band must still act as a click and start no drag. A drag that did not move past a few pixels is a click. Evidence: PR 501 merged as 8c4fe495; `test_a_drag_by_the_band_moves_the_box` and `test_a_press_on_a_band_button_is_a_click_and_starts_no_drag` (tests/page/test_page_move_box.py) were red before the code; 98 passed on t-compute in the three touched page files, CI run 44791201332 success (slice 3 re-run once after a runner apt lock); boss_review round 1 GO.
- [x] Keep the box inside the viewport while dragging and on drop. The band gets a `move` cursor (not on its buttons). Evidence: `test_the_box_stays_inside_the_screen` and `test_the_band_has_a_move_cursor_and_its_buttons_keep_theirs` passed. The box is clamped while it moves; a re-clamp after a resize or rotation is a follow-up.
- [x] A drag starts no text selection and opens no comment button for one (`selectionchange` and `mouseup` offers, the touch release path in SPEC 9). Evidence: `test_a_drag_selects_no_text_and_offers_no_comment_button` was red (selection text came back) before the code, green after.
- [x] The box stays where it was dropped for as long as it is open, including while the page re-renders (`replace()` calls `place()`) and while a reply arrives. The next open places it as today; nothing is stored. Evidence: `test_the_box_keeps_its_place_when_a_reply_arrives` and `test_the_next_open_places_the_box_as_usual` passed.
- [x] Tests in the page suite, run in CI or on t-compute only: a drag moves the box; a click on a band button still works; the box keeps its place across a re-render; the dragged place comes back after `undock()`; a drag while docked does nothing. Evidence: tests/page/test_page_move_box.py (7 tests) and, in test_page_keyboard.py, `test_a_docked_box_is_not_moved_by_its_band_and_shows_no_move_cursor` and `test_the_dragged_place_comes_back_when_the_keyboard_closes` all passed; every test drives a mouse, none a touch.
