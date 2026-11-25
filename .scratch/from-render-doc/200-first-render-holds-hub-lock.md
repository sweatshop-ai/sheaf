# 200: a first render runs pandoc under the hub's lock and stops every document's requests

**Claimed by:** Mei

**Status:** open (claimed, ticket written, no code yet)

**Blocked by:** none

**From:** ticket 199, point left as found (#673). The problem predates #673. #673 makes it last longer than the request that caused it: after a `pending` answer, the render continues on its worker thread and keeps the lock.

**Where:** `src/sheafmd/hub/core.py` (`Hub.entry`, `Hub._entry`, `Hub._bound`), `tests/test_hub_index.py`.

## Problem

`Hub._entry` makes the entry of a document the hub has not opened yet entirely inside `with self._lock:` (the hub-wide `RLock`). This includes `e.live.refresh(force=True)`, the first render. So every pandoc run of that render (`render.py`: the JSON pass and the HTML pass, plus one run per table that `comments._read_tables` reads) happens with the hub's lock held. Each run is allowed 120 s (`_pandoc.TIMEOUT`), and the runs have no shared limit (199).

## Effect on other requests

While a first render is running, every thread that needs `self._lock` waits until the render ends:

- **Every request for any document**, opened or not. `Hub.entry` → `_entry` takes `self._lock` even for an entry that already exists (the lookup at the top of `_entry`). The handler reaches it through `Handler._entry` on 13 routes: `_page` (the page itself), `_document_stream` (the events stream), `_doc_state`, `_entry_to_write` (saves), `_export`, `_jump`, `_mount`, `_pin`, `_retarget`, `_seen`, `_sessions`, `_target` and `_thread_job` (comment jobs). Also `forwards.py`, `tell.py` (`_entry`, the jobs of a Tell), `_say_stopped` and `_record_james` in the handler, and `Hub._render_entry` (the render of `sheaf open`).
- **Commits of writes with private roots**: `_bound`, called from `Hub.committed`, takes the lock.
- **`Hub.render` of any other document**, `forget_document`, `_let_go_root`, `moved_page` and `moved_remote`.

**How long:** the sum of the first render's pandoc runs, each up to 120 s, with no total limit. A page with a slow pandoc (a large document, an overloaded machine) stops the whole hub for that time, for every person and every open page. Before #673, the request of the `sheaf open` that caused it was waiting too. Since #673, that request answers `pending` after 120 s, and the hub stays stopped until pandoc ends.

## Rules

- A first render of document A never delays a request for another document B (opened or not) beyond the time needed to make an entry, without pandoc.
- The guarantees `_entry` gives under the lock stay: an address whose root was forgotten (`forget_root`) in the meantime names nothing (NotFound), and two requests that open the same new document together end up with one entry, rendered once.

## Direction (for the implementer to confirm or replace)

Do the first render outside `self._lock`, under the document's own lock (`place.held(address)`, already taken by `Hub.entry`). Then take `self._lock` only to check the root again and insert the entry, or to return the entry that another thread inserted first. One way to do this is a "being made" marker per address, so that a second opener of the same document waits for the first one instead of rendering again. The private-root rebinding check at the top of `_entry` runs without pandoc and can stay under the lock.

## Boxes

- [ ] **A** Failing test first, in `tests/test_hub_index.py`: a first render of document A whose fake pandoc is held by an `Event` runs on a thread. A request for document B, already opened (`hub.entry(B)`, and a render of B with unchanged settings), answers within 1 s while A's pandoc is held. On main, it waits until the `Event` is set.
- [ ] **B** Same test shape for a document B that was not opened before: its own first render runs while A's pandoc is held (two first renders in parallel).
- [ ] **C** Tests that keep the guarantees: (1) `forget_root` during A's held first render makes A's address NotFound and inserts no entry; (2) two threads opening the same new document while its pandoc is held produce one entry and one render (pandoc call count).
- [ ] **D** Fix in `Hub._entry` (see Direction). `place.held` stays thread-bound, as in 199.
- [ ] SPEC: if a section states that the hub's lock covers the first render, say what it covers now; otherwise nothing.
