# 101: Restes c/d de la PR 327 (ticket 80) : refus rejoué après un Undo, rejeux sans fin, refus propre de la page, test rouge du reset

**What to build:** Revue Opus de la PR 327 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-80-reviews/opus-round1.md`. Rien de classe a ni b. Pour chaque point : corriger, ou écrire la limite dans le SPEC 10.11.
1. (c) `src/sheafmd/page/page.js:3771` : `pressSaid` est remis à zéro dans `send()`, pas au clic ; un press annulé (Undo, ~3815-3820) laisse le refus A en place, alors que le SPEC dit qu'un nouveau press l'oublie. Remettre à zéro au clic, ou écrire « un press envoyé ».
2. (c) `page.js:672, 4476` : le toast rejoué reçoit un nouveau `until` à l'affichage ; chaque rechargement dans cette fenêtre le redit, sans limite (un agent qui écrit le fichier toutes les 5 s le garde à l'écran), et chaque rejeu poste un incident `toast` à `/_/diag` (659). Le SPEC dit « dans les mêmes 7 secondes » : faux. Borner (garder l'`until` d'origine) ou écrire la limite.
3. (c) `page.js:3786-3790` : le refus propre de la page (« The actions changed while <label> waited ») ne pose jamais `pressSaid`, donc n'est jamais redit ; le SPEC dit « le refus du dernier press ». Le poser aussi, ou limiter le SPEC aux refus du hub.
4. (d) `tests/page/test_page_actions.py:326` : A a expiré (`run_for(7000)`) avant le rechargement, donc `|| reloadPending` suffit à rendre le test vert ; la remise à zéro n'a pas de test rouge. Scénario du ticket 80 : A refusé, B réussit, le `changed` de B recharge dans la fenêtre de A.
5. (d) `test_page_actions.py:354,357` : `run_for(100)` par essai, au moins 26 essais dans 8 s : fragile sur un coureur chargé. Avancer de 3000 ms comme le premier test ; l'idiome `or p.clock.run_for(100) and False` est illisible.
6. (d) `SPEC.md:1380` : virgule en trop : « (7 seconds), (a refusal still queued… ».

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** le point 4, le test rouge du reset ; sur t-compute, jamais sur le portable.

- [ ] Chaque point : corrigé (test rouge d'abord) ou la limite écrite dans le SPEC
