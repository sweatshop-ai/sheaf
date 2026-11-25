# Handoff: ticket 193, Codex NO-GO on #599 and #601

**Status:** done. PR #660 merged as 9d674600, through the merge gate on review round 1 (an Opus-fallback GO, provisional; Codex was limited). Matt's code review: no hard violations. Its minor points were applied in 3500c9a3.

## Outcome per original PR

- #599: both findings already fixed, by e15ea754 and 5f8f1a18 (ticket 181 A). Their tests in `tests/test_hub_place.py` pass on main.
- #601: the serious finding and the minor one are fixed in #660. A key a newer stream takes is barred on the older streams of the same owner, bounded per stream.

## Open

Nothing.
