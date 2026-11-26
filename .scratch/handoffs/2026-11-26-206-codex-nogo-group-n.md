# Handoff: ticket 206, Codex NO-GO group N (a shared stream reopened during a join), 2026-11-26

**Claimed by:** Kenji. **State:** done, merged in #690 (bf5af361).

## Result per original PR

- #660, finding 1 (a join resumed on a stream reopened under its id took the key from the fresh stream): fixed in #690 (206 A).
- Codex on #690 found the same window for a stream closed after the check (206 A2): fixed in #690.

## Review

One round. Matt's code review (standards minors applied, spec GO), Codex on the branch NO-GO (A2), fixed test-first, Codex on the fix commit GO. Merged through `boss_merge` on the gate's recorded round, an Opus provisional GO (the gate's own Codex call hit the default account's limit).

CI on the merged head: 11339 passed, one failure, `test_land_root`, which fails on main until #677 lands.

## Also filed

- Ticket 207, no fix: two lone escaped shortcodes in two changed stretches of about 1 000 words each keep only one escape (found during ticket 205).

## Open

- None in 206.
