# The movable comment box: no re-clamp after a resize, and no test for touch, the mounted page or a pinned box

**What to build:** Close the gaps that the review of PR 501 (ticket 174, the box moved by its band) left open. Each one is separate, and none changes how the drag behaves today with a mouse on a desktop page.

**Blocked by:** None.

**Status:** open

- [ ] A moved box is re-clamped after a window resize or a phone rotation. Today the box is held inside the visible area only while it moves; `replace()` skips `place()` once `_moved` is set, and `undock()` can hand back a place that lies outside a rotated screen. DONE WHEN: a test in the page suite drags the box to the lower right, shrinks the viewport (and, on the touch fixture, rotates it), and the box lies fully inside the visible area afterwards; a box that was dropped inside the new area does not move.
  - Partly done in #617 (b96f36bb, ticket 183 X): a moved box is held inside again after a window resize and after it grows or shrinks, with tests in `tests/page/test_page_move_box.py`. Still open: rotation on the touch fixture, and `undock()` handing back a place outside a rotated screen (and the room it restores, 183 BP). None of these is tested yet.
- [ ] A drag by touch is tested. Every test of ticket 174 drives a mouse. DONE WHEN: a test on the touch fixture presses the band with a touch pointer, moves it, and the box moves; a tap on a band button is still a click; a touch that starts in the page's words outside the box still scrolls the page (`touch-action: none` on the band only); and a `pointercancel` in the middle of a drag leaves the box where it was and starts no later drag.
- [ ] A drag on the mounted page (the page drawn in a shadow root, `ROOT` is not `document`) is tested. DONE WHEN: a test mounts the page in a host with an offset (not at the screen's origin) and drags the box: it follows the pointer and stays inside the host's visible area.
- [ ] A pinned box (a thread or kept comment with no place in the text, fixed beside the panel by `pin()`) is tested. DONE WHEN: a test opens such a box, drags it, and it moves, stays inside the visible area, keeps its place through a re-render, and is pinned again at the next open. In the mounted page a fixed box is clamped against the host's body but positioned in viewport coordinates, which agrees only when no ancestor of the host has a transform: the test names that case or the code handles it.
