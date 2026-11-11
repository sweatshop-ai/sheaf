# 23: Les événements « vu » et « annulé » d'un Tell ne nomment pas l'agent : un fil qui attend deux agents les confond

**What to build:** Un fil peut attendre deux agents (cible changée après un premier Tell). La page garde une seule place par fil (`waits[id]`), et les événements `tell-seen`, `tell-cancelled` et `tell-done` ne portent que l'identifiant du fil (`page.js`, gestionnaires depuis 03247a83 ; `waiting.py`, `take` et `_end`). Trouvé par la revue Codex du ticket 18 (P1) ; l'état n'est pas dû à la branche des tickets 17 à 20.

**Blocked by:**
- 04

**Status:** ready-for-agent

Scénario : les agents A et B ont chacun un Tell en attente sur c1 ; `tell-queued` de B met B dans la place du fil ; A appelle `documents` : `tell-seen {id: c1}` marque B comme « vu ». Même confusion à l'annulation et à la fin. Le ticket 18 ne restaure plus `seen` d'un agent pour l'autre dans un instantané, mais ne change pas les événements. À décider : une place par couple fil et agent côté page, avec l'agent dans les trois événements côté hub, ou refuser un second agent sur un fil qui attend déjà.

- [ ] Décision écrite, avec un test rouge puis vert (deux agents sur un fil, A voit son Tell : la ligne de B reste « en attente »)
