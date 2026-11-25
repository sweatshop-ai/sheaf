# Handoff: ticket 192 done, pin age in a root's store and SIGTERM in a route callback (2026-11-25)

**Status:** done. #659 merged as c0c9dca0 through the gate (round02 GO, provisional Opus fallback; CI green on b87746d9).

## Done

- #590 (pin age, round06 NO-GO): fixed in #659. A pin in a root's own store has its time in `<hash>.at` beside it, kept out of git by `.sheaf/versions/.gitignore`; a clone or checkout brings no time, so no old pin is believed again.
- #592 (RouteGreenlet, round05 NO-GO): fixed in #659. A SIGTERM in a route callback's greenlet is raised again when that greenlet switches away; a second SIGTERM before that is raised where the test stands.
- Ticket `.scratch/from-render-doc/192-codex-nogo-pin-age-and-route-greenlet.md`: both boxes ticked with evidence and two MINORs left open.

## Worth knowing

- The ticket asked for a pin time "git carries". The first review round showed why that is wrong: each hub's time differs, so two clones pinning one version conflict and stop pushing. The time is local on purpose; a pin made on another clone is not believed on this one.
- Pins written before #659 have no time file: after an upgrade, a page holding its reload across the hub restart can get the 409 until its next daily pin. The CHANGELOG says so.
- `tests/test_leakguard.py` sets a SIGTERM handler, so run it with `-p no:xdist` locally.
