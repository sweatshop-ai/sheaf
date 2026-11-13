# 91: Roots follow-ups: the brand rule, a cancel that is never refused, a forget that waits on a render

**Status:** open

**From:** render-doc ticket 91 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `SPEC.md:696`, `SPEC.md:1591`, `src/sheafmd/hub/index.py:81`, `src/sheafmd/hub/handler.py:1691-1701`, `src/sheafmd/hub/tell.py:415`, `SPEC.md:666`, `src/sheafmd/hub/core.py:815`, `:857-880`, `src/sheafmd/hub/live.py:468`

**Size:** three items; two are decisions before code

- [ ] **The spec contradicts itself on the brand.** `SPEC.md:1591` (section 13, the CLI) says `sheaf --help` and every output stay free of the maker's brand name; `SPEC.md:696` (section 8.6) and `src/sheafmd/hub/index.py:81` (`CREDIT`) put "Made by <brand>. A hosted version is coming." in the index page's footer (also the README, per section 19). The owner decides which rule stands (for example, narrow section 13 to CLI output), then the spec text is aligned. Seen by reading both spec lines.

- [ ] **`POST /_/cancel` is never refused (design question).** A page still open on a document of a forgotten root can cancel the running or waiting Tell of a different folder's document that took the same root name and has a thread with the same comment id: `src/sheafmd/hub/handler.py:1691-1701` (`_cancel`) and `src/sheafmd/hub/tell.py:415` (`cancel(address, cid)`) match by address and id only, and `SPEC.md:666` says a cancel succeeds "whether the document, its file or its root is still there". Decide whether a cancel should carry the page's version (or the root's identity) and be refused after a `gone`, as reply, edit, Ask and Tell already are.

- [ ] **A root forget waits for a running render while holding the hub lock.** `Hub.forget_root` (`src/sheafmd/hub/core.py:857-880`) takes `Hub._lock`, then for each entry calls `LiveDocument.forget()` (`src/sheafmd/hub/live.py:468`), which takes the document's lock; a render of that document (pandoc, up to 120 s) holds that lock, so every request that needs to make or find an entry stalls until the render ends. `Hub.render` (`core.py:815`) does the same on a rebuild. Moving the version drop outside the hub lock races with a new folder's document taking the same address, so the fix first needs versions of two folders under one address to be told apart. Reproduce: start a slow render (a large doc or a slow pandoc shim), run `sheaf roots forget <root>`, time a second document's page load.
