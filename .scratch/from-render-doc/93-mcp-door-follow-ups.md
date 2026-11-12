# 93: MCP door follow-ups: a second file lister, a second status dot, a CLI proof on two connections

**Status:** open

**From:** render-doc ticket 93 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/mcp.py:51`, `:214`, `:554`, `:620-622`; `src/sheafmd/hub/roots.py:541`, `:603`, `:614`; `src/sheafmd/hub/index.py:264-282`; `src/sheafmd/hub/client.py:177`, `:216`, `:325`, `:386`

**Size:** three items, each one session; parked until after the launch when they were filed

- [ ] **The MCP door lists a root's markdown files with its own lister.** `src/sheafmd/mcp.py:214` `markdown_files` has its own git-ls-files and walk lister, next to the one in `src/sheafmd/hub/roots.py` (`_git_names` `:541`, `_walk` `:603`, `_capped` `:614`). The door's copy has no "more" marker past the 2000-file walk cap, and in a git root its ls-files call does not exclude `.sheaf/**` the way `_git_names` does. Make the door call the roots/index lister.

- [ ] **The status-dot cascade is written twice, and the copies have drifted.** `src/sheafmd/mcp.py:554` `Door._dot` and `src/sheafmd/hub/index.py:264-282` `Index._row` (`DOT_ORDER` is still at `mcp.py:51`). For a member, the index uses `member_seen` and `member.name` for unread and hides the hub account's session question; the door's `_documents` (`mcp.py:620-622`) uses `hub.seen` and `hub.person`, and `_dot` reads `session_question()` for everyone. One function should give the dot for both. To see the difference: compare `documents` through a member-bound token with that member's index page, on a document that has unread threads.

- [ ] **A CLI command proves the hub on one connection and sends its request on another.** `HubClient.challenge()` (`src/sheafmd/hub/client.py:177`) proves the hub, then `HubClient.call()` (`:216`) does a second proof on a new connection and carries no expected boot id. A hub restart between the two means `stop_and_explain` (`:325`) and `_meet_version` (`:386`) mix the pid, boot and version of one hub with answers from another. No key leaks, because both hubs hold the same key, but the wrong process can be waited on. Fix: `call` carries the boot id it expects and the hub refuses on a mismatch, or the command reuses the proved connection.
