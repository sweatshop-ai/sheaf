# 47: Quand le pilote Playwright de la session se fige, chaque test de page suivant attend ses 300 s, et le job va jusqu'à ses 60 min sans rien nommer

**What to build:** le run 43288137873 (PR 258, tranche 2/3, tentative 1, annulée à 60 min dans l'étape « Page tests ») s'est figé sur un seul test, puis a perdu 53 min à faire expirer dix tests de suite, chacun à la limite par test de `pyproject.toml` (`timeout = 300`). La limite par test existe et fonctionne ; elle ne suffit pas parce que le pilote Playwright est celui de la session (`tests/page/conftest.py:89`, fixture `chromium` à portée `session`, un seul `sync_playwright().start()`) : une fois qu'il ne répond plus, tous les tests qui restent attendent la même réponse qui ne vient pas, et la limite les fait échouer l'un après l'autre à raison de 5 min. Le test de départ est nommé ci-dessous ; aucun message ne dit « le pilote est figé, arrêtez ».

**Blocked by:** none

**Classe :** c (CI : un coût de 60 min de runner et d'attente, aucun défaut de produit établi).

**Établi (preuves) :** journal de la tentative 1, job 131426897645 (`gh api repos/sweatshop-ai/sheaf/actions/jobs/131426897645/logs`) :
- 19:24:35 l'étape commence ; les tests passent jusqu'à 19:27:06 (`test_page_actions.py::test_every_reload_asked_during_a_press_counts_and_the_settle_still_saves_the_edits PASSED`). L'étape dure d'ordinaire 7 à 8 min (main 3b7a6cc, run 43281135217 : 7 m 41 s ; PR 250, run 43287876811 : 7 m 11 s).
- Le test suivant, `tests/page/test_page_actions.py::test_a_box_typed_in_a_block_whose_save_is_merged_is_not_ticked_before_the_reload`, ne finit jamais : FAILED puis ERROR à 19:28:00, et à 19:31:36 le message de `the_main_thread_names_its_frame` dit « still running after 270 s ; the main thread is in » `playwright/sync_api/_context_manager.py:56 greenlet_main` → `run_until_complete` → `selector.poll` : le fil principal attend le pilote Playwright, pas le hub (les fils du hub, `_serve`, `_watch`, `_accept`, sont tous au repos dans le même vidage).
- Ensuite chaque test expire à 300 s : 19:33:00, 19:38:00, 19:43:00, 19:48:00, 19:53:00, 19:58:00, 20:03:00, 20:08:01, 20:13:01, 20:18:01 (dix `Timeout`, sur `test_page_actions.py` puis `test_page_agent.py`), jusqu'à `test_page_boot.py::test_a_hub_that_goes_and_comes_back_has_a_new_boot PASSED` à 20:18:01 ; le job est annulé à 20:22:18 par `timeout-minutes: 60`.
- Ce n'est pas le verrou : `uv.lock` ne change aucune version de paquet (PR 258 ne change que le contrainte de `pytest-xdist`), et la tentative 2 est la preuve ou non d'un hasard (voir le statut).
- Cause du premier figement : non établie. Le journal n'a pas la pile du test (le `FAILED` n'a pas de traceback : la sortie `-v` des tests échoués vient en fin d'exécution, que l'annulation a coupée).

**Par où commencer :** deux gestes, indépendants.
1. Arrêter l'étape au premier `Timeout` qui touche le pilote : `--maxfail=2` ne suffit pas (un échec ordinaire compte) ; un crochet `pytest_runtest_logreport` dans `tests/page/conftest.py` qui, au premier test expiré dont le fil principal est dans `greenlet_main`, appelle `pytest.exit("le pilote Playwright ne répond plus", returncode=1)`. Le run échoue au bout de 5 min au lieu de 60, avec la phrase qui nomme la cause.
2. Garder la pile du test qui s'est figé : imprimer le traceback des tests échoués au moment où ils échouent (`-rfE` ne suffit pas ; `--tb=short` avec `-o console_output_style` n'imprime pas non plus avant la fin), ou écrire à la fin du test expiré `request.node.nodeid` + la pile principale, ce que `the_main_thread_names_its_frame` fait déjà à 90 % de la limite.

- [ ] Un pilote Playwright qui ne répond plus arrête l'étape « Page tests » au premier test expiré, avec un message qui le dit
- [ ] Un test de `tests/` pose le cas à la main (un faux pilote qui bloque) et échoue sans le crochet
- [ ] Le test qui s'est figé la première fois est nommé dans le journal sans qu'on ait à lire 7 800 lignes

**Claimed by:** —

**Status:** ready
