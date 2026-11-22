# 101: Restes c/d de la PR 327 (ticket 80) : refus rejoué après un Undo, rejeux sans fin, refus propre de la page, test rouge du reset

**What to build:** Revue Opus de la PR 327 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-80-reviews/opus-round1.md`. Rien de classe a ni b. Pour chaque point : corriger, ou écrire la limite dans le SPEC 10.11.
1. (c) `src/sheafmd/page/page.js:3771` : `pressSaid` est remis à zéro dans `send()`, pas au clic ; un press annulé (Undo, ~3815-3820) laisse le refus A en place, alors que le SPEC dit qu'un nouveau press l'oublie. Remettre à zéro au clic, ou écrire « un press envoyé ».
2. (c) `page.js:672, 4476` : le toast rejoué reçoit un nouveau `until` à l'affichage ; chaque rechargement dans cette fenêtre le redit, sans limite (un agent qui écrit le fichier toutes les 5 s le garde à l'écran), et chaque rejeu poste un incident `toast` à `/_/diag` (659). Le SPEC dit « dans les mêmes 7 secondes » : faux. Borner (garder l'`until` d'origine) ou écrire la limite.
3. (c) `page.js:3786-3790` : le refus propre de la page (« The actions changed while <label> waited ») ne pose jamais `pressSaid`, donc n'est jamais redit ; le SPEC dit « le refus du dernier press ». Le poser aussi, ou limiter le SPEC aux refus du hub.
4. (d) `tests/page/test_page_actions.py:326` : A a expiré (`run_for(7000)`) avant le rechargement, donc `|| reloadPending` suffit à rendre le test vert ; la remise à zéro n'a pas de test rouge. Scénario du ticket 80 : A refusé, B réussit, le `changed` de B recharge dans la fenêtre de A.
5. (d) `test_page_actions.py:354,357` : `run_for(100)` par essai, au moins 26 essais dans 8 s : fragile sur un coureur chargé. Avancer de 3000 ms comme le premier test ; l'idiome `or p.clock.run_for(100) and False` est illisible.
6. (d) `SPEC.md:1380` : virgule en trop : « (7 seconds), (a refusal still queued… ».

**Blocked by:** none


**Claimed by:** Enzo 2026-11-14 21:05

**Status:** done (merged 3e6980b, PR 339; leftovers in ticket 112)

**Par où commencer :** le point 4, le test rouge du reset ; sur le serveur auto-hébergé, jamais sur le portable.

- [x] Chaque point : corrigé (test rouge d'abord) ou la limite écrite dans le SPEC (vérifié sur origin/main, commit ad83e80 de la PR 339, merge 3e6980b ; reste d'un point : ticket 143) :
  - [x] 1 : fait. `page.js:3847` remet `pressSaid` à zéro dans `send()` ; le SPEC 10.11 (l. 1381) écrit « a press that goes past its Undo forgets an earlier one's refusal (a press undone does not…) ». Test : `tests/page/test_page_actions.py:345`.
  - [x] 2 : fait pour la limite : `page.js:4562` garde l'échéance d'origine (`until: refusedPress.until`), le SPEC dit « the deadline is the one it was first said under, so reloads do not chain it on ». Test : `test_page_actions.py:376`. Reste : chaque rejeu poste encore un incident `toast` à `/_/diag` (`page.js:660`, `say(…, true)` du rejeu à 4559) : ~~le rejeu ne poste pas d'incident~~ (struck: moved to ticket 143).
  - [x] 3 : limite écrite dans le SPEC 10.11 (l. 1381) : « the page's own "The actions changed while <label> waited" is not kept » ; `page.js:3858` ne pose pas `pressSaid`, comme écrit.
  - [x] 4 : fait. Test rouge du reset : `test_page_actions.py:345` `test_an_earlier_refusal_still_up_is_not_said_again_by_the_reload_of_a_later_press_that_succeeded` (« without [the reset] the reload carries A », A encore affiché à 5,1 s de ses 7) ; `:324` pour B.
  - [x] 5 : fait. Plus de `run_for(100)` par essai ni de `or … and False` dans ces tests : boucles à `run_for(3000)` (`test_page_actions.py:324`, 345 et suivants).
  - [x] 6 : fait. SPEC.md 10.11 (l. 1381) lit « (7 seconds; a refusal still queued behind other toasts counts as up, …) », la virgule en trop est partie (commit ad83e80).
