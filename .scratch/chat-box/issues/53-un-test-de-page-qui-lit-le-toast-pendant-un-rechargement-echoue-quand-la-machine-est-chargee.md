# 53: Un test de page qui lit le toast pendant un rechargement échoue quand la machine est chargée

**What to build:** `toast(page)` (`tests/page/pagehelp.py:253`) évalue `document.querySelector('#rd-toast').textContent` dans la page. Appelée dans un `until` juste après `reloaded(p)`, l'évaluation tombe sur la page qui se recharge : `TypeError: Cannot read properties of null (reading 'textContent')` (pas encore de `#rd-toast`) ou `Execution context was destroyed, most likely because of a navigation`. `until` ne rattrape pas ces erreurs (il attend un résultat faux, pas une exception), donc le test échoue au premier sondage tombé sur le rechargement. Sous charge, la fenêtre est assez large pour que cela arrive une fois sur deux.

**Blocked by:** none

**Classe :** c (CI : un rouge sans lien avec le changement poussé).

**Établi (preuves) :** sur t-compute (`~/work/elif-52`, afbe595 + PR 267, hors CI), huit passages de `tests/page/test_page_actions.py` entier, quatre brûleurs de CPU en parallèle, `--timeout=120` : quatre rouges sur huit, chacun de 1 test sur 40 (39 passed) :
- `test_a_replys_answer_that_reloads_the_page_waits_for_a_press_in_its_undo` (ligne 205 : `until(lambda: "reload the page" in toast(p), ...)`) : `Page.evaluate: TypeError: Cannot read properties of null (reading 'textContent')`, passages 2 et 4 ;
- `test_a_change_from_outside_during_a_press_waits_for_its_answer_before_the_page_reloads` (ligne 151 : même ligne) : `Page.evaluate: Execution context was destroyed, most likely because of a navigation`, passages 5 et 6.
Les deux tests sont ceux qui précèdent immédiatement le test du ticket 52 dans le fichier ; la même ligne de sondage. Sans charge (premier passage, 43 s) tout passe.

**Par où commencer :** `toast()` ne doit pas lever pendant un rechargement : l'attraper dans la fonction que `until` appelle (rendre `""` quand l'évaluation échoue pour ces deux raisons), ou un `toast_text(page)` pour les attentes. Test de `tests/` qui pose le cas à la main (une page dont le `#rd-toast` n'existe pas encore). Ne pas élargir l'attrapage à toute erreur Playwright : un pilote figé doit rester visible.

- [ ] La lecture du toast pendant un rechargement rend « pas encore » au lieu de lever, pour les deux erreurs relevées et pour elles seules
- [ ] Un test pose le cas à la main et échoue sans le correctif
- [ ] Huit passages du fichier entier sous quatre brûleurs sur t-compute, aucun rouge de ce type

**Claimed by:** Elias 2026-11-13 01:35

**Status:** in-progress
