# 80: Rejeu du refus d'un bouton après un rechargement : `pressSaid` jamais remis à zéro, refus rejoué non regardé pour un second rechargement, message remplacé, test à attente réelle (restes du tour 3 de la PR 298)

**What to build:** Restes de classe c et d du tour 3 de revue (Opus) de la PR 298, `pm/chat-box-handoffs/pr-62-reviews/opus-round3-narrow.md`. Aucun a ni b. Pour chaque point : corriger, ou écrire la limite dans le SPEC (10.11, « une fois de plus sur la page qu'un rechargement en attente apporte tant que ce toast serait encore là »).
- c : `pressSaid` (`src/sheafmd/page/page.js`, posé vers 3742, lu vers 935) n'est jamais remis à zéro. Un rechargement quelconque pendant que le toast du refus A est en file ou à l'écran rejoue A, pas seulement le rechargement qui attendait le bouton. Exemple : le bouton A est refusé pendant qu'un formulaire retient le rechargement, le bouton B réussit, son `changed` recharge la page dans la fenêtre de A : la page neuve redit A. Et un refus B plus tardif, sans rechargement en attente, laisse A en place : B est perdu au rechargement tant que A n'a pas expiré.
- c : un refus rejoué sur la page neuve n'est pas gardé de nouveau si un second rechargement vient vite (le `pressSaid` de la page neuve est nul).
- c (ancien) : le rejeu remplace `msg` (nouvelles de commentaires, texte du rechargement tenu) au lieu de mettre les deux en file (`page.js:4405-4406`). Les toasts qui attendaient sur l'ancienne page sont perdus au rechargement : voulu, à écrire.
- d : `tests/page/test_page_actions.py:287-289` attend 500 ms de temps réel l'événement `changed` pendant que l'horloge est arrêtée ; sur un coureur chargé, un événement en retard laisse `reloadAfterPress` nul et le test devient rouge à tort.
- d : commentaire faux à `tests/page/test_page_actions.py:296` (« the page's own toast of the change first, then the refusal ») : `page.js:4405` dit le refus à la place de `msg`, pas après.
- d : commentaire faux à `tests/page/test_page_writing.py:2683` (l'horloge « stands still ») : `given_up` appelle `reload_on_clock(p)` sans pause, voir ticket 79.

**Blocked by:** none


**Claimed by:** Aurelio 2026-11-14 18:51

**Status:** done (merged into main as 16fb935, PR 327)

**Par où commencer :** le point `pressSaid` jamais remis à zéro : écrire le test rouge (A refusé, B réussi, rechargement dans la fenêtre de A), sur le serveur auto-hébergé, jamais sur le portable.

- [x] Chaque point c : corrigé avec son test rouge d'abord, ou la limite écrite dans le SPEC — PR 327 (16fb935) : `page.js:3847` remet `pressSaid` à zéro à chaque appui ; `:3886` le pose aussi quand un rechargement est en attente ; `:4559-4562` met `msg` puis le refus en file et regarde le refus rejoué pour un second rechargement ; tests `tests/page/test_page_actions.py:324` et `:361` ; limite des toasts perdus au rechargement écrite dans SPEC.md:1381
- [x] `tests/page/test_page_actions.py:287-289` n'attend plus 500 ms de temps réel — PR 327 : attend l'événement `changed` par `until(lambda: heard(p, "changed"))` (`tests/page/test_page_actions.py:285`, `HEARD` à `:56`)
- [x] Les deux commentaires faux sont corrigés — `tests/page/test_page_writing.py:2702` dit que `given_up` laisse l'horloge à son pas réel ; le commentaire de `tests/page/test_page_actions.py:293` (toast du rechargement d'abord, puis le refus) est vrai depuis `page.js:4559-4562` (PR 327)
