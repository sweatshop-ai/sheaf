# 39: Le groupe xdist des fichiers `IN_ORDER` repose sur deux internes de xdist, et `pytest-xdist>=3.6` n'a pas de borne haute

**What to build:** PR 253 (ticket 38) garde un fichier `IN_ORDER = True` sur un seul worker xdist. `tests/conftest.py::pytest_configure` passe `--dist` à `loadgroup` sur le contrôleur, et met `config.option.loadgroup = True` sur un worker, parce qu'un worker calcule son `loadgroup` à partir des arguments avec lesquels il a été lancé (`xdist/remote.py`, `setup_config`, xdist 3.8.0). Le correctif dépend donc de deux internes : `setup_config` tourne avant `pytest_configure`, et `remote.py` lit `getvalue("loadgroup")`. `pyproject.toml` dit `pytest-xdist>=3.6`, sans borne haute. Une version qui renomme l'option ou transmet `dist` par `workerinput` casserait le groupe sans bruit ; seul `tests/test_in_order.py` le verrait, et il le voit (il échoue dès que le fichier est coupé).

**Blocked by:** none (PR 253 merged into main as 3b7a6cc)

**Établi (preuves) :**
- Revue Opus de 6bad373 (repli, Codex sans jetons), P2 sur `tests/conftest.py:106` : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-38-reviews/opus-fallback-6bad373.md`. Classe c.
- Le test de régression échoue chaque fois sans l'une des deux moitiés du correctif (relu par la revue dans `scheduler/load.py`, trois tests sur deux workers répartis en tourniquet).
- Pas de défaillance observée : c'est une dépendance, pas un bug.

**Par où commencer :** soit borner `pytest-xdist` (`>=3.6,<4`) et faire relire le correctif à chaque montée de version majeure, soit remplacer la partie worker par un marqueur que xdist documente seul (`pytest.mark.xdist_group` avec `--dist loadgroup` donné sur la ligne de commande de CI et du README des tests), en gardant un test qui coupe le fichier.

- [x] Le choix (borne ou ligne de commande) est écrit avec sa raison : borne `>=3.6,<4`, `uv.lock` régénéré (PR 258) ; la ligne de commande aurait remis `--dist` sur chaque commande, ce qui a déjà cassé `-p no:xdist` (ticket 38)
- [x] `tests/test_in_order.py` échoue toujours si le groupe cesse de fonctionner
- [x] CI verte

**Claimed by:** Isolde 2026-11-12 20:12

**Status:** done (PR 258, merged 0455284)
