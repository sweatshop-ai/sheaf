# 38: `tests/test_isolation.py::test_the_hub_that_test_started_was_stopped_when_it_ended` échoue de temps en temps en CI

**What to build:** Le test a échoué en CI sur la PR #248 (run 43232192468, tête 2864294, job 131230119897, tranche 1/3, py3.13, 2026-11-12) : `1 failed, 2649 passed, 5 skipped`, `assert STARTED and gone(STARTED[0])` avec `assert ([])`, donc `STARTED` vide. Halima rapporte une seconde observation le même jour (Hakim, PR #249, tête 78eb9c0 : tests d'arrêt de hub de `test_service` et `test_isolation` rouges, verts à la tête suivante ; non relue ici). Classe : c (instable, aucun lien avec le diff de la PR #248, dont le delta 06a ae1dae2..2864294 ne touche que `tests/test_hub_transcribe.py`).

**Blocked by:** aucun

**Établi (preuves) :**
- Job 131230119897, `tests/test_isolation.py`, `assert ([])` sur `STARTED`, worker `gw0`.
- Le même test a passé dans les autres runs de 06a lus (par exemple 43223482785) ; le fichier n'a pas changé.
- Non reproduit.

**Lecture du code (une lecture, pas une preuve) :** `STARTED` est une liste de module, remplie par `test_a_command_that_starts_a_hub_starts_it_on_that_port`, et le test en échec commence par un commentaire « Relies on the file's order: the test before this one started the hub ». Sous xdist, deux tests du même fichier peuvent aller à deux workers : le second voit alors la liste de son propre processus, vide. Ce qui concorde avec `assert ([])`. Ce que le planificateur de xdist fait ici (mode `load`, `loadfile` ou `loadgroup`) n'a pas été lu dans le workflow `ci.yml` ni dans `pyproject.toml`.

**Par où commencer :** lire les options xdist de CI, puis soit regrouper les deux tests (`pytest.mark.xdist_group` avec `--dist loadgroup`), soit les fondre en un seul test qui démarre le hub, relève le pid et vérifie l'arrêt dans la même fonction. Vérifier si le test voisin de `test_service` a le même défaut.

- [x] La cause est écrite avec la preuve (la liste des tests par worker d'un run rouge, ou une reproduction avec `-n 2`) ; la lecture ci-dessus est confirmée ou corrigée
- [x] Le test n'a plus besoin de l'ordre du fichier ni d'un état partagé entre deux tests ; il passe quel que soit le worker
- [x] Les deux tests d'arrêt de hub de `test_service` sont relus pour le même défaut
- [x] Les preuves de passage tournent en CI ou sur t-compute, pas ici ; CI verte sur deux passages de suite

**Claimed by:** Isolde 2026-11-12 16:03

**Status:** done — PR 253 merged by Thierry, main 3b7a6cc; main CI run 43281135217 3/3 green; PR runs 43247947522 attempts 1 and 2 (6bad373), 43278368964 (35fb054)

**Cause (reproduite, 2026-11-12):** CI lance `pytest -n 4` (`--dist load`) ; `IN_ORDER` ne garde un fichier entier que dans une tranche, pas sur un worker xdist. Trois tests de `test_isolation.py` sous `-n 2` donnent le même `assert ([])` que le run 43232192468. La lecture du code (Nia) est confirmée.

**Correctif :** `pytest_itemcollected` marque les tests d'un module `IN_ORDER` `xdist_group(<module>)` ; `pytest_configure` (tests/conftest.py) passe `--dist` à `loadgroup` sur le contrôleur et `loadgroup` sur le worker. Les trois paires qui lisent la liste d'un test précédent (deux dans `test_isolation`, une dans `test_service`) sont couvertes. Test : tests/test_in_order.py. Pas dans `addopts` : `-p no:xdist` ne démarrerait plus.

**CI :** run 43247947522 sur 6bad373, tentative 1 verte (3/3) et tentative 2 verte (3/3). Revues : Codex indisponible (jeton), repli Opus GO ; revue des standards PASS ; trois P2 notées (worksteal explicite, suffixe de groupe dans les ids, dépendance aux internes de xdist), non corrigées (c/d). Fichiers : /home/tiroir/.claude/pm/chat-box-handoffs/pr-38-reviews/.
