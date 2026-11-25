# Handoff: ticket 196, Codex NO-GO group H (2026-11-25)

**State:** C and E fixed and merged in #668 (merge d61773bc). A, B, D were already fixed on main. F and G left open, both minor; reasons in the ticket.

**Per original PR:**
- #621: A already fixed by 0082c3a2; B already fixed by 25d10469.
- #626: C fixed in #668.
- #630: D already fixed by bad6b30c; E fixed in #668.
- #633: F left open (Delete's retry cannot tell a replaced page from its own autosave: every save renames a new inode in; needs a page identity that survives saves).

**Review:** round 1 provisional (Opus fallback, Codex out of tokens until 2026-11-26 00:42Z). Codex should recheck #668 once back.

**Next:** F and G need a design choice (an identity that survives a save; an id check in Roots.forget). Neither is a wrong result in ordinary use.
