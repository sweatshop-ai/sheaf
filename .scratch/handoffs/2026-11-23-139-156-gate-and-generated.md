# Handoff: ticket 139 line 51 and ticket 156 follow-ups, 2026-11-23

Worker Cleo, track sheaf-backlog.

## Merged

| PR | Ticket box | Head | Merge |
|---|---|---|---|
| #638 | 139 line 51: `or no.uid == 0` dropped from `_gate` | 765ceca9 | 12f2757b |
| #639 | 156: both notices on a read-only generated page; locked pressed one-offs kept on The List | 61b6f8de | 57833f96 |

Both have review round 1, provisional GO (Opus fallback through `boss_review`; Codex out of tokens until
2026-11-27 14:15), and CI green on the head. The first CI runs died when the runners lost contact during
the page tests; the reruns passed.

## Left open on 156

- 403 before 400 on `/_/sessions`: no fix warranted, reason in the ticket.
- `_record_james` and the setter's next `update`: no fix warranted, reason in the ticket, pinned by a test.
- New box from #639's review: a generated rectoverso's page should draw the locked pressed one-offs as
  The List does (`core.py` `meta["actions"] = []`), and SPEC 10.1 say so.

## Security note on 139

The change only narrows the 503 path: an OTHER_USER refusal never returns from `_gate`, so nothing that
was refused is let in. OTHER_USER with uid 0 means a root process still held the socket at accept time.
