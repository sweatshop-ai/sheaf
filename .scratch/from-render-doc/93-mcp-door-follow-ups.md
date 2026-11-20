# 93: MCP door follow-ups: a second file lister, a second status dot, a CLI proof on two connections

**Claimed by:** Piotr 2026-11-20 17:44

**Status:** in-progress

**Blocked by:** none

**From:** render-doc ticket 93 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/mcp.py:51`, `:214`, `:554`, `:620-622`; `src/sheafmd/hub/roots.py:541`, `:603`, `:614`; `src/sheafmd/hub/index.py:264-282`; `src/sheafmd/hub/client.py:177`, `:216`, `:325`, `:386`

**Size:** three items, each one session; parked until after the launch when they were filed

- [x] **The MCP door lists a root's markdown files with its own lister.** `src/sheafmd/mcp.py:214` `markdown_files` has its own git-ls-files and walk lister, next to the one in `src/sheafmd/hub/roots.py` (`_git_names` `:541`, `_walk` `:603`, `_capped` `:614`). The door's copy has no "more" marker past the 2000-file walk cap, and in a git root its ls-files call does not exclude `.sheaf/**` the way `_git_names` does. Make the door call the roots/index lister.

  Done in #492, merged as 7e00742f. The door's `documents` calls `list_documents(src, cap=COUNT_LIMIT)`: the hub's rules (`.sheaf/**` excluded; a git root that git cannot answer lists nothing, as SPEC 8.6 says), with `tests/test_mcp_documents.py` green (30 tests; the open-comment-past-the-cap test was red before). **"No more marker past the walk cap" is moot:** a review found the shared 2000 cap hid a waiting Tell or an open comment past it, and the door is an agent's view, so it lists up to the hub's count limit (100,000) instead; a `{root, more}` row fires only past that. SPEC `documents` row says so. Follow-up for what the review left: `.scratch/follow-ups/door-documents-silent-root-and-unbounded-walk.md`.

- [ ] **The status-dot cascade is written twice, and the copies have drifted.** `src/sheafmd/mcp.py:554` `Door._dot` and `src/sheafmd/hub/index.py:264-282` `Index._row` (`DOT_ORDER` is still at `mcp.py:51`). For a member, the index uses `member_seen` and `member.name` for unread and hides the hub account's session question; the door's `_documents` (`mcp.py:620-622`) uses `hub.seen` and `hub.person`, and `_dot` reads `session_question()` for everyone. One function should give the dot for both. To see the difference: compare `documents` through a member-bound token with that member's index page, on a document that has unread threads.

- [ ] **A CLI command proves the hub on one connection and sends its request on another.** `HubClient.challenge()` (`src/sheafmd/hub/client.py:177`) proves the hub, then `HubClient.call()` (`:216`) does a second proof on a new connection and carries no expected boot id. A hub restart between the two means `stop_and_explain` (`:325`) and `_meet_version` (`:386`) mix the pid, boot and version of one hub with answers from another. No key leaks, because both hubs hold the same key, but the wrong process can be waited on. Fix: `call` carries the boot id it expects and the hub refuses on a mismatch, or the command reuses the proved connection.
