# The door's `documents` drops a root silently when git fails, and walks a plain folder with no time bound

**What to build:** two defects left by #492 (the door's `documents` now lists with the hub's lister, `list_documents(src, cap=COUNT_LIMIT)` in `src/sheafmd/mcp.py`, `Door._documents`).

1. **A git root that git cannot answer drops with no word.** When git times out, refuses (`safe.directory`) or is missing, `list_documents` returns an empty listing (SPEC 8.6: the root lists nothing it has not vouched for). The door then gives no row for the root: no `closed` row, no `more` row. An agent can miss Tells and open comments waiting there and is not told. Give the root a row of its own (the `{root, closed}` shape, with the reason as short as the folder case) or say in the SPEC `documents` row that it is silent. Test: the `GIT_FAILS` cases in `tests/test_mcp_documents.py` (`test_a_document_in_a_git_directory_is_not_listed_...`) already build the situation.
2. **A plain folder is walked and opened with no time bound.** Before #492 a non-git root stopped at a 2000-file walk; now `_documents` walks and opens (`_open_in`) up to `COUNT_LIMIT` (100,000) files per call, and counts up to 100,000 more. A root that is a home directory or holds vendored trees makes one `documents` call slow. Bound the call: a time budget that stops the walk and says so in a `{root, more}` row, or open only files whose stat shows an open comment is possible.

Lower priority, same code:

3. `more` is a lower bound past 100,000 (`_capped` stops counting at `COUNT_LIMIT`), while the tool description and SPEC call it a count of what was left out. Say "at least".
4. For a member, the overflow of their private root is dropped when the list root is another member's loose root (the `not giving` check looks at the list root, not at the private root), and the private roots' overflow is summed under the list root's name. Neither has a test; add one with a member-bound token.

**Blocked by:** None.

**Status:** open

- [ ] A git root that git cannot answer says so in the door's `documents`, or SPEC says why it does not
- [ ] One `documents` call on a large plain folder is bounded in time, and the answer says when it stopped
- [ ] `more` says it is a lower bound where it is
- [ ] The member-bound `more` cases (private-root overflow, another member's loose root) have tests
