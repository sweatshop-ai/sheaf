# Open tickets carried over from the development repo

These are the open tickets carried over from the private development repo when it was archived. Each ticket there was checked on 2026-11-12 against this repo's `main` at `81afdff`; only the items still open for sheaf itself are here, with their paths and line numbers re-checked on that commit. Items that were done, moot, or about a private deployment were left behind.

| File | Title | Items | What |
|---|---|---|---|
| [91-roots-follow-ups.md](91-roots-follow-ups.md) | Roots follow-ups | 3 | The brand rule contradicts itself in SPEC; `/_/cancel` is never refused; a root forget waits on a render under the hub lock |
| [93-mcp-door-follow-ups.md](93-mcp-door-follow-ups.md) | MCP door follow-ups | 3 | The door has its own file lister and its own status dot; a CLI command proves the hub on two connections |
| [94-hub-publishes-a-half-written-file.md](94-hub-publishes-a-half-written-file.md) | The hub can publish a half-written file | 1 | An in-place rewrite read mid-write is published to open pages |
| [96-packaging-macos-and-windows.md](96-packaging-macos-and-windows.md) | Packaging: macOS and Windows | 5 | No green macOS run on main, launchd and Windows never run for real, real names in SPEC examples |
| [99-lifecycle-review-follow-ups.md](99-lifecycle-review-follow-ups.md) | Lifecycle review follow-ups | 20 | Peer-check gaps, restart announcements without a generation, stop races, refactors, lint |
| [101-macos-ci-on-main.md](101-macos-ci-on-main.md) | macOS on main | 3 | Run macOS CI on main on every Python; fix the "never green" comments; readings only a real Mac can check |
| [137-edit-pin-and-writer-follow-ups.md](137-edit-pin-and-writer-follow-ups.md) | Page edits, pins and writers | 21 | Backslashes lost on an edit (P2), emoji, no-break spaces, split-line merges, pins, `os.fchmod` on Windows |
| [139-peer-uid-check-on-every-request.md](139-peer-uid-check-on-every-request.md) | Peer-uid check on every request | 5 | One decision and one probe, then the build of the per-request OS-user check |
| [142-paste-from-real-programs.md](142-paste-from-real-programs.md) | Paste from real programs | 1 | Paste from a real web mail client and online word processor, by hand |
| [144-enter-in-task-lists-edge-cases.md](144-enter-in-task-lists-edge-cases.md) | Enter in task lists | 3 | Nested and ordered lists, an emptied item with a comment, a loose item |
| [146-kept-draft-and-leading-comment-anchor.md](146-kept-draft-and-leading-comment-anchor.md) | Kept draft and leading anchor | 2 | A kept comment draft can land on the wrong paragraph; a leading anchor stops a typed task line |
| [155-private-names-in-the-public-tree.md](155-private-names-in-the-public-tree.md) | Private names in the public tree | 2 | Real names and a private host name are back in fixtures and SPEC; add a deny-list test |
| [156-generated-page-read-only.md](156-generated-page-read-only.md) | Generated pages read-only | 4 | A per-document "generated" mark so a job's rebuild cannot silently overwrite a person's edit |
| [160-live-streams-use-up-browser-connections.md](160-live-streams-use-up-browser-connections.md) | Seventh tab never loads | 2 | One live stream per tab uses up Chrome's six connections per host |
| [162-commit-follow-ups.md](162-commit-follow-ups.md) | Commit follow-ups | 3 | A commit in a root that took a forgotten name; `root.git` fixed at registration; versions store chosen once |
| [164-list-action-inside-a-code-fence.md](164-list-action-inside-a-code-fence.md) | List action inside a code fence | 1 | A task line in a fenced block inside a list item becomes a false action |
| [167-door-refusal-names-membership.md](167-door-refusal-names-membership.md) | Door refusal for a non-member | 2 | A non-member's `create` should name the project, not a missing root |
