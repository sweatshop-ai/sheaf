# Handoff: ticket 191, Codex NO-GO findings of group D (2026-11-25)

**Ticket:** `.scratch/from-render-doc/191-codex-nogo-group-d-text-round-trip-2.md`
**PR:** #658 (branch `hugo/191-codex-nogo-group-d`, head 4162d810)

## Outcome per original PR

| PR | Finding | Result |
|---|---|---|
| #576 | typed backslash before a bold shortcode | already fixed by fe75ec79 |
| #581 | `http://localhost` written bare | already fixed by 8b8777eb |
| #581 | address with a space and a backslash | fixed in #658 |
| #591 | FTP link dropped beside a bare `<a>` | already fixed by a3420561 |
| #591 | `IndexError` on literal token characters | already fixed by 58cb9a44 |
| #594 | typed shortcode saved as text in a long change | fixed in #658 (word diff) |
| #594 | backslash ending a block escaped the next shortcode | fixed in #658 |
| #595 | escaped quote in a CSS value | fixed in #658 |
| #595 | `lighter` inside a heavy weight | fixed in #658 (`bolder` too) |

## Review round

- Matt's code-review: standards smells fixed; the spec review showed the first #594 fix (neighbours only) turned the
  failure round, replaced by a word diff (d875bf92).
- Codex unavailable (account b at its limit until 14:06 local). Hand-run Opus bug hunt: GO, two P2s (words split at
  white space only) fixed in 4162d810. Note: the boss review store.
- The gate's recorded round: `boss_review.py --track sheaf-backlog` (Opus fallback while Codex is limited).
  Codex still owes a follow-up pass on #658 once it is back; its findings become tickets.

## Open

- [MINOR] #581 variant: an address with a backslash and a line break is still left to pandoc (`\%0A`); only a
  pasted `<a>` reaches it.
- #594: past about 1 400 words on each side of a changed part, a literal placed neither by words nor by its
  neighbours is written bare.

## Merge

- PR #658 merged by the gate as 4b7e3fcc (round 1, Opus fallback, GO, no findings; record in the boss review store).
- CI: run 45588476774, attempt 1 lost its self-hosted runner at 65% of the unit tests with no test failed;
  attempt 2 green.
- Ticket 191 ticked, status done. Codex owes a follow-up pass on #658 once its account is back; its findings
  become a new ticket.
