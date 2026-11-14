# 02: A tick box's label ticks it

**What to build:** on a plain task line, the label (the words before the first `:` or ` — `, else the first word) is clickable and ticks or unticks the box, like a `<label>`. The rest of the line is ordinary text: a click there does nothing, a selection opens the chat box, a link opens. Example: in `- [ ] Approved: the quote of 12 November`, "Approved" ticks the box.

**Blocked by:** None (can start immediately).

**Status:** done

- [x] A click on the label ticks; a second click unticks (a plain box, not an action) (`test_a_click_on_the_label_ticks_and_a_second_click_unticks, passed in CI on 42db03c`)
- [x] A click on the rest of the line does not tick (`test_a_click_on_the_rest_of_the_line_ticks_nothing, passed in CI on 42db03c`)
- [x] A drag-selection that starts on the label opens the chat box and does not tick (`test_a_drag_selection_from_the_label_opens_the_chat_box_and_ticks_nothing, passed in CI on 42db03c`)
- [x] Works on a phone (touch target at least 44 px high, as the action buttons) (`test_on_a_phone_the_label_is_44_px_high_to_touch (touch context, tap below the words), passed in CI on 42db03c`)
