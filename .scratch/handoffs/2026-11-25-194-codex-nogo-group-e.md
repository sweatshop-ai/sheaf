# Handoff: ticket 194, Codex NO-GO group E (#570, #605, #606, #607, #610)

**Status:** merged in ee5a5df6 (#661, head 7e17ad72, CI run 45643072460 green, gate round 03 provisional GO).

## Outcome per original PR

| PR | Outcome |
|---|---|
| #570 | Fixed in #661 (194 A, B, C): temp file 0o600 until read back, mode through the read-back descriptor, text encoded before anything opens |
| #605 | Already fixed by 730328dd (ticket 182 H): a forget takes the moves' lock the move holds |
| #606 | Partly fixed in #661 (194 G, launchd). Open: G2, Linux cannot tell `systemctl stop` or an older unit from a restarted signal |
| #607 | Fixed in #661 (194 D, E): `_text_after` looks past the end of the marks a break ends, inside its own cell |
| #610 | Fixed in #661 (194 F, the `stopped` row). Open: H, the memory bound needs a streaming lister |

## Review

One round: Matt's code-review (standards clean; spec: SPEC 8.4 amended for launchd), bug hunt by the Opus fallback (Codex at its usage limit): GO. Codex should run on #661 once it is back, as a follow-up; findings become tickets.

## Gate notes

- Rounds 01 and 02 recorded a GO but GitHub answered 500 on the comment (GraphQL and REST, any body); round 03 posted. `gh pr merge` then answered 502 although the merge landed, so `merges.jsonl` says `failed` for a merge that happened.
- One probe comment from diagnosing the 500s is still on #661 (GitHub refused its delete).

## Open

- G2 and H in ticket 194, each with its reason. H wants its own ticket for a streaming lister.
- I to L in ticket 194: the merge gate's minors (chmod refusal message, root and a mode without owner read, `_text_after` past a block in a cell, the darwin test's process-wide patch).
- Codex re-reviews #661 once its limit resets; findings become tickets.
