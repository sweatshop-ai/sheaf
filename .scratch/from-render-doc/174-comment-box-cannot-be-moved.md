# 174: The comment box cannot be moved


**Claimed by:** Zeynep 2026-11-20 18:32

**Status:** in-progress

**Blocked by:** none

**From:** asked by the owner, 2026-11-20

**Where (main bb3eafb8):** `src/sheafmd/page/page.js` (`place`, `replace`, `pin`, `dock`/`undock`, `bandHtml`), `src/sheafmd/page/page.css:69` (`#rd-popover`) and `:127-131` (`.rd-head`), `SPEC.md:1262`

**Size:** one decision on touch screens, then a drag handler, its CSS and tests

An open comment box can cover the text the owner wants to read. They want to grab the box by its top band and drag it elsewhere.

## To do

- [ ] Decide how the drag behaves where the box is docked to the head of the visual viewport (a touch screen with the keyboard up, `dock()`): the box is fixed there and `replace()` rewrites its position on every `visualViewport` event.
- [ ] Drag the box by its band with pointer events, so mouse and touch both work. A press on a band button (Resolve, Close, the ⋯ menu) or on a link in the band must still act as a click and start no drag. A drag that did not move past a few pixels is a click.
- [ ] Keep the box inside the viewport while dragging and on drop. The band gets a `move` cursor (not on its buttons).
- [ ] A drag starts no text selection and opens no comment button for one (`selectionchange` and `mouseup` offers, the touch release path in SPEC 9).
- [ ] The box stays where it was dropped for as long as it is open, including while the page re-renders (`replace()` calls `place()`) and while a reply arrives. The next open places it as today; nothing is stored.
- [ ] Tests in the page suite, run in CI or on t-compute only: a drag moves the box; a click on a band button still works; the box keeps its place across a re-render.
