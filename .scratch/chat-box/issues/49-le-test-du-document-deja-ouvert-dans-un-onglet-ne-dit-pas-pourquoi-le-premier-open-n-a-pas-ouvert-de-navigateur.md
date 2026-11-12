# 49: Le test « un document déjà ouvert dans un onglet n'est pas rouvert » échoue en CI sans dire pourquoi le premier `sheaf open` n'a pas ouvert de navigateur

**What to build:** `tests/test_cli_hub.py::test_a_document_already_open_in_a_tab_is_not_opened_again` a échoué une fois en CI avec `IndexError` à `opened_browser.opened[0]` (ligne 85) : le premier `sheaf open` n'a jamais appelé `webbrowser.open`. PR 248, run 43317866368, job 131530625354 (py3.13, tranche 2, xdist 4 workers). Première occurrence sur les 30 derniers runs en échec ; 46/46 × 3 en local sur 06a et sur main ; aucun chemin de 06a n'y mène. Le test n'imprime ni `r.out` ni `r.err` : la cause est perdue. Classe : c (diagnostic de test, aucun changement de produit).

**Blocked by:** none

**Claimed by:** Isolde 2026-11-12

**Status:** in-progress

**Établi (preuves) :** dans `_open` (`src/sheafmd/cli.py`), le navigateur n'est pas ouvert quand `tabs > 0` (un flux `/_/live` déjà compté), quand `seat.remote(os.environ)` n'est pas `None` (SSH sans variable de navigateur), quand `--no-browser`, `SHEAF_NO_BROWSER=1` ou `browser = false`, ou quand le lien de connexion est refusé (`r.err`). Les deux premiers se lisent dans `r.out` ; le reste dans `r.err` et dans l'environnement.

**Par où commencer :** les tests qui indexent `opened[0]` (lignes 85, 126, 139, 419 de `tests/test_cli_hub.py`) lisent le lien par une aide qui, si rien n'a été ouvert, échoue avec `r.out`, `r.err`, le siège distant, `browser_enabled` et les variables concernées. Modèle : le message de `test_a_browser_that_cannot_be_started_says_so_and_still_exits_0`. Test seul.

- [ ] Un échec forcé montre `r.out`, `r.err` et l'état des onglets, du siège et du navigateur dans le message
- [ ] Les tests de `tests/test_cli_hub.py` qui lisent `opened[0]` passent par cette aide
