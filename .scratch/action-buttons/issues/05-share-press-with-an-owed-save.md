# 05: A Share press with an owed save says so, and is tested

**What to build:** `pressShare` (src/sheafmd/page/page.js) saves a block with unsaved edits before it sends Share's tick, and stops when that save did not succeed (sweatshop-ai/sheaf#293, 11ff860: an owed save, hub unreachable, no longer lets the press go on, so the owed edits are never merged over a ticked file). Two things are left from that change.

**Blocked by:** sweatshop-ai/sheaf#293 merged.

**Status:** done

- [x] The click is not dropped silently: with the hub unreachable and a block with unsaved edits, pressing Share's box says so (for instance "The hub is unreachable: press Share again once it is back.") and the box keeps its state. Today `pressShare` returns without `say()` when `save(true, res)` returns false with `res.owed` set and the save was silent, until the outage banner appears after its grace time. (class b, Review 4, Sonnet, on 11ff860)
  Done in sweatshop-ai/sheaf#318, merged as 1c66392 (head 24ed8dc): `pressShare` says it at page.js:3745; Codex review 1 GO on 24ed8dc (https://github.com/sweatshop-ai/sheaf/pull/318#issuecomment-6882930910); green in CI on 24ed8dc: https://github.com/sweatshop-ai/sheaf/actions/runs/43617201478.
- [x] A page test covers the owed path: the hub route aborted, a Share block with unsaved edits, Share's box pressed; assert that no `/_/tick` goes out, the box is unchanged, the edits stay unsaved and are saved once the route is back, and the file is not ticked. (class c, Review 4)
  Done in #318 (1c66392): tests/page/test_page_actions.py::test_share_pressed_with_the_hub_unreachable_and_an_owed_save_says_so_and_ticks_nothing, green in CI on 24ed8dc: https://github.com/sweatshop-ai/sheaf/actions/runs/43617201478. Limit: the owed edit is saved by the autosave timer, not by `payOwed` at the hello.

Not affected, read in the code: only Share reaches `pressShare` (`toggleOf` is set for toggle actions only, page.js:3686); Merge, Deploy, Install and the other one-off words go through `tickBox` and `pressable`, unchanged.
