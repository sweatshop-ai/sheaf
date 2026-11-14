# 05: A Share press with an owed save says so, and is tested

**What to build:** `pressShare` (src/sheafmd/page/page.js) saves a block with unsaved edits before it sends Share's tick, and stops when that save did not succeed (sweatshop-ai/sheaf#293, 11ff860: an owed save, hub unreachable, no longer lets the press go on, so the owed edits are never merged over a ticked file). Two things are left from that change.

**Blocked by:** sweatshop-ai/sheaf#293 merged.

**Status:** ready-for-agent

- [ ] The click is not dropped silently: with the hub unreachable and a block with unsaved edits, pressing Share's box says so (for instance "The hub is unreachable: press Share again once it is back.") and the box keeps its state. Today `pressShare` returns without `say()` when `save(true, res)` returns false with `res.owed` set and the save was silent, until the outage banner appears after its grace time. (class b, Review 4, Sonnet, on 11ff860)
- [ ] A page test covers the owed path: the hub route aborted, a Share block with unsaved edits, Share's box pressed; assert that no `/_/tick` goes out, the box is unchanged, the edits stay unsaved and are saved once the route is back, and the file is not ticked. (class c, Review 4)

Not affected, read in the code: only Share reaches `pressShare` (`toggleOf` is set for toggle actions only, page.js:3686); Merge, Deploy, Install and the other one-off words go through `tickBox` and `pressable`, unchanged.
