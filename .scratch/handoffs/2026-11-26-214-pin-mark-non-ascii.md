# Handoff: ticket 214, a non-ASCII pin mark (2026-11-26)

## Status

Done on branch `kenji/214-pin-mark`. The Codex check of #701 (ticket 213) raised one P2. A `.at` whose mark held a non-ASCII character made `hmac.compare_digest` raise `TypeError`, so reading or trimming that document's pins failed. A mark is now refused unless it is 32 hex, and is compared as bytes. Test first, red on main.

## Next

Nothing. Ticket 213's handoff is `.scratch/handoffs/2026-11-26-213-codex-nogo-group-s.md`.
