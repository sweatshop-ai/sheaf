# 23: Les événements « vu » et « annulé » d'un Tell ne nomment pas l'agent : un fil qui attend deux agents les confond

**What to build:** Un fil peut attendre deux agents (cible changée après un premier Tell). La page garde une seule place par fil (`waits[id]`), et les événements `tell-seen`, `tell-cancelled` et `tell-done` ne portent que l'identifiant du fil (`page.js`, gestionnaires depuis 03247a83 ; `waiting.py`, `take` et `_end`). Trouvé par la revue Codex du ticket 18 (P1) ; l'état n'est pas dû à la branche des tickets 17 à 20.

**Blocked by:**
- 04

**Status:** ready-for-agent

Scénario : les agents A et B ont chacun un Tell en attente sur c1 ; `tell-queued` de B met B dans la place du fil ; A appelle `documents` : `tell-seen {id: c1}` marque B comme « vu ». Même confusion à l'annulation et à la fin. Le ticket 18 ne restaure plus `seen` d'un agent pour l'autre dans un instantané, mais ne change pas les événements. Décision d'Isolde (2026-11-11) : on garde plusieurs agents par fil. Chaque couple fil et agent a sa propre place côté page, et le hub nomme l'agent dans `tell-seen`, `tell-cancelled` et `tell-done`. Refuser un second agent est écarté. Ticket envoyé après la PR des tickets 17 à 20 (`chat-box/tell-flakes`), pas dedans.

- [x] Décision écrite (ci-dessus)
À regarder avec ce ticket (revue Opus du 2026-11-11, côté hub, antérieur à la branche) : `waiting.take` publie `tell-seen` avant `write_json`, et l'instantané de `changed` lit `tells.json` sans le verrou des attentes (`waiting.py:218`, `:259`, `core.py:484`, `live.py:183`, `mcp.py:636`). Un instantané peut donc dire « queued » juste après `tell-seen` et remettre la ligne à « en attente » jusqu'au prochain événement. Écrire avant d'émettre, lire sous le verrou.

- [ ] Le test rouge puis vert, avec un test rouge puis vert (deux agents sur un fil, A voit son Tell : la ligne de B reste « en attente »)
