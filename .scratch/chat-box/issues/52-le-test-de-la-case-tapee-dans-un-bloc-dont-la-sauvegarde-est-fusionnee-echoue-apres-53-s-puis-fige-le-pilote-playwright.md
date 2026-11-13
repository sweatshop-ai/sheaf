# 52: Le test de la case tapée dans un bloc dont la sauvegarde est fusionnée échoue après 53 s, puis le pilote Playwright ne répond plus

**What to build:** `tests/page/test_page_actions.py::test_a_box_typed_in_a_block_whose_save_is_merged_is_not_ticked_before_the_reload` (ligne 357 sur main afbe595) est le test qui a figé le pilote Playwright de la session deux fois en une journée, sur deux runs de main ou de PR sans rapport l'un avec l'autre. Les deux fois le même enchaînement : il échoue environ 53 s après le test précédent (bien avant la limite de 300 s), son démontage échoue dans la même seconde, puis le fil principal reste dans `greenlet_main` / `selector.poll` sans jamais en sortir, et chaque test suivant expire à 300 s. Le ticket 47 (PR 260, afbe595) arrête désormais le run au premier test expiré ; il ne dit pas pourquoi ce test échoue ni pourquoi le pilote ne répond plus ensuite. Ce ticket cherche la cause.

**Blocked by:**

- External: PR 267 merged into main and a page-test freeze seen in CI with the traceback

**Classe :** c (CI : un run de 60 min annulé à chaque apparition ; la cause n'est pas établie).

**Établi (preuves) :**
- Première apparition : run 43288137873 (PR 258, tentative 1), job 131426897645. `PASSED` du test précédent (`test_every_reload_asked_during_a_press_counts_and_the_settle_still_saves_the_edits`) à 19:27:06 ; le test ci-dessus `FAILED` puis `ERROR` à 19:28:00 (54 s plus tard) ; à 19:31:36 (270 s après le début du test) le message de `the_main_thread_names_its_frame` donne le fil principal dans `playwright/sync_api/_context_manager.py:56 greenlet_main` → `run_until_complete` → `selector.poll`.
- Deuxième apparition : run 43326825430 sur main 4fbc1a1 (poussée, avant la fusion de la PR 260), tranche 2/3, job 131561262634. `PASSED` du même test précédent à 23:16:33 ; le test ci-dessus `FAILED` puis `ERROR` à 23:17:26 (53 s plus tard) ; à 23:21:03 (270 s après le début) même pile : `greenlet_main` → `run_until_complete` → `selector.poll` ; puis un `Timeout` à 23:22:27 et un toutes les 5 min (onze `ERROR` à 5 min d'intervalle) jusqu'à l'annulation à 00:12:29 par `timeout-minutes: 60`. Les tranches 1 et 3 du même run sont vertes. Sur la pile de ce test, les fils du hub (`_serve` → `_stream` → `sub.get`, `_accept`) sont au repos : le hub n'attend rien.
- Le même test et le même délai (53 à 54 s) les deux fois : ce n'est pas un hasard de planification. Le test passe dans les autres runs (quatre runs verts le même jour pour le premier, main afbe595 verte pour le second).
- Le journal n'a pas la cause de l'échec à 53 s : le `FAILED` n'a pas de traceback (la sortie `-v` des tests échoués vient en fin d'exécution, que l'annulation a coupée). Avec le ticket 47 le run s'arrête au premier test expiré mais la pile affichée est celle de ce test-là (le suivant), pas celle de l'échec de 53 s.

**Établi le 2026-11-13 (Elif, lecture du code de `tests/page/pagehelp.py` et reproduction sur t-compute) :**
- Les 53 s sont l'addition des bornes du dépôt, pas un hasard : `until` (8 s) + `STALL_GRACE` (5 s) = 13 s avant `PageStalled`, puis `close_context` : `unroute_all` borné à `CLOSE_BOUND` (20 s), puis `context.close()` borné à 20 s : 13 + 20 + 20 = 53 s, FAILED à la fin du premier délai, ERROR à la fin du dernier. Donc, dans ce test, un appel Playwright d'un `until` n'est jamais revenu, et le démontage non plus : le pilote était déjà figé pendant le test, avant les 300 s des tests suivants.
- Reste à établir quel appel s'est figé. Le crochet de la PR 267 (étape 1) imprime maintenant le traceback du premier test de page échoué (il porte le « timed out waiting for ... »), donc la prochaine apparition le nomme.
- Piste `route.fetch()` : non confirmée. 40 passages du test seul, sous quatre brûleurs de CPU sur t-compute, tous verts ; 8 passages du fichier entier sous la même charge : quatre rouges, mais sur deux autres tests (voir le ticket 53), aucun sur celui-ci et aucun figement. Le dépôt connaît déjà un gestionnaire de route qui ne finit pas (commentaire de `close_context`, CI de la PR 227 : 360 s).

**Établi le 2026-11-13 (Elias, reproduction du figement sous charge sur t-compute, PR 268) :**
- Commande, sur une copie de la branche chat-box/53 (`git archive HEAD | ssh t-compute 'tar -x -C ~/work/sheaf-53'`, puis `uv sync --locked`), script `~/work/sheaf-53/loop53.sh` (copie : `~/work/sheaf-53/keep/loop53.sh`) : quatre brûleurs de CPU (`timeout 1700 sh -c "while :; do :; done" &` x4), puis huit fois `timeout 400 uv run --no-sync pytest -q -p no:cacheprovider --timeout=120 -n 2 tests/page/test_page_actions.py`.
- Deux boucles de huit passages (16 runs) : le pilote Playwright s'est figé deux fois, aux passages 7 et 8 de la première boucle (171 s et 172 s, les deux fois `timeout 400` non atteint, arrêt par `tests/driver_stall.py`). Les 14 autres passages ne se sont pas figés (24 à 34 s chacun).
- Le test en cours au moment du figement, les deux fois : `test_a_reload_asked_only_by_an_upgrade_saves_what_was_typed_during_the_press` (`.` x39 puis `E`). Lignes du journal : `--- tests/page/test_page_actions.py::test_a_reload_asked_only_by_an_upgrade_saves_what_was_typed_during_the_press: still running after 108 s; the main thread is in:` suivie de la pile `playwright/sync_api/_context_manager.py:56 greenlet_main` → `run_until_complete` → `selector.poll` ; puis `--- tests/page/test_page_actions.py::test_a_saved_action_box_is_not_ticked_while_a_press_holds_the_reload_of_its_merged_save: timed out in the Playwright driver (setup)` et `!!! the Playwright driver no longer answers ... and every test after it would wait the same !!!`. Même pile que dans les deux apparitions de CI ci-dessus.
- Ce n'est pas le test de ce ticket (celui de la ligne 357) mais celui qui l'avoisine : il pose aussi `p.route("**/_/doc?*", lambda r: r.abort())` et `p.clock.run_for`, puis tape pendant l'attente du rechargement. Il passe dans les 14 autres passages.
- Limites : les journaux des passages 7 et 8 de la première boucle ont été écrasés par la deuxième boucle (même nom `file-N.log`) ; les lignes ci-dessus sont celles lues avant l'écrasement. Pas de passage de la branche main sous la même charge : on ne sait pas si le figement existe sans la PR 268 (qui ne change que `toast()` et ses tests). Le fichier est exécuté avec `-n 2`, que la reproduction du ticket 53 sans `-n` n'utilisait pas.

**Par où commencer :**
1. Faire dire l'échec de 53 s : imprimer, dès le premier `FAILED` ou `ERROR` d'un test de page, son traceback (même crochet `pytest_runtest_logreport` que `tests/driver_stall.py`), pour que la prochaine apparition porte la cause dans le journal.
2. Lire le test : il pose `p.route("**/_/save", merged, times=1)` dont le gestionnaire appelle `route.fetch()` à l'intérieur du rappel (API synchrone, dans le répartiteur du pilote), puis tape dans le bloc, coche la case et attend `reloaded(p)` ; 53 s ressemble à deux attentes de 20 à 30 s. Établir par une expérience sur t-compute (jamais ici) si le gestionnaire de route peut se bloquer lui-même quand la sauvegarde arrive pendant un appel synchrone en cours (par exemple en le répétant 50 fois sous charge avec le crochet de l'étape 1) avant de conclure quoi que ce soit.
3. Corriger la cause, pas le délai.

- [ ] La cause de l'échec à 53 s est écrite avec la preuve (le traceback d'une apparition, ou une reproduction sur t-compute)
- [ ] Le correctif est dans le test ou dans la page, et un test pose le cas à la main
- [ ] CI verte sur deux passages de suite, la tranche qui porte ce fichier comprise
- [ ] Un test de page qui échoue montre son traceback dans le journal dès son échec, sans attendre la fin du run

**Claimed by:** Elif 2026-11-13 01:15

**Status:** blocked (PR 267 + next sighting)
