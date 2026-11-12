# 32: Le hub écrit deux lignes `push-failed` pour une sauvegarde dont le dépôt distant est absent, de temps en temps en CI

**What to build:** `tests/test_hub_commits.py::test_a_push_that_fails_is_a_row_the_save_stands_and_the_next_push_carries_it` a échoué en CI sur la PR #250 (run 43219583500, tête 7ca451e, job 131187381864, tranche 2/3, py3.13, 2026-11-12) : `1 failed, 2704 passed`. Le test déplace le dépôt distant, sauvegarde une fois, attend `settle()`, puis lit `(row,) = rows("push-failed")` (ligne 169) : `ValueError: too many values to unpack (expected 1)`. Le hub a donc écrit deux lignes `push-failed` ou plus pour une seule sauvegarde. Classe : c (instable, déjà sur main).

**Blocked by:** aucun

**Status:** ready-for-agent

**Établi (preuves) :**
- Job 131187381864, `tests/test_hub_commits.py:169`, `ValueError: too many values to unpack (expected 1)`, `1 failed, 2704 passed, 2 skipped`. Le journal ne dit ni le nombre de lignes ni leur texte.
- Le diff de la PR #250 (`gh pr diff 250`) ne touche que le ticket 21, `src/sheafmd/page/page.js` et `tests/page/test_page_chat_box.py` : rien dans `hub/commits.py`, `core.py`, `handler.py` ni ce test.
- Le même test a passé dans la tranche 2/3 de trois runs de main : 81afdff (43219154279), 523f7f6 (43209571975) et 597d52a (43212771285, rouge pour un autre test, celui du ticket 31). Les runs plus anciens n'ont pas été lus.
- Non reproduit.

**Lecture du code (une lecture, pas une preuve) :** dans `src/sheafmd/hub/commits.py`, `_pusher` (autour de la ligne 497) fait `record = self._record if wrote else self._once(repo)` : l'échec d'une passe qui suit une écriture est écrit à chaque fois, sans déduplication (le sondage, lui, passe par `_once`). `_push_later` met une passe par dépôt dans `_due` et y fond les écritures. Si une seconde passe commence avant la fin de la première, chacune échoue sur le dépôt absent (`_pull`, ligne 587, ou le push, lignes 528 et 540) et écrit sa ligne. Ce qui déclenche la seconde passe n'est pas trouvé : `/_/save` ne commite qu'une fois (`handler.py:927`) et le hub du test n'a pas de fil qui appelle `tick()` (seul `server.py:324` le fait hors tests), donc le sondage n'est pas la cause. La fenêtre est une affaire de temps, ce qui va avec une machine chargée et un seul échec vu.

**Par où commencer :** lire le code pour savoir pourquoi une seconde passe a lieu après une seule sauvegarde (qui appelle `_push_later` ou rend `_due` non vide, et si la passe peut se rejouer sur une erreur de `_pull`), avec la sortie du test en boucle sur t-compute ou en CI pour attraper les lignes écrites. Le correctif se fait dans le hub, pas en relâchant le décompte du test (`len(rows) == 1` reste exact).

- [ ] La cause est écrite avec la preuve : les deux lignes relevées (texte, ordre) et ce qui a déclenché la seconde passe
- [ ] Le correctif est dans le hub : une sauvegarde dont le push échoue écrit une seule ligne `push-failed`, quelle que soit la charge ; le test garde `(row,) = rows("push-failed")`
- [ ] Un test pose la fenêtre à la main (deux passes de suite sur un dépôt absent) et échoue sans le correctif
- [ ] Les preuves de passage tournent en CI ou sur t-compute (jamais ici) ; CI verte sur deux passages de suite
