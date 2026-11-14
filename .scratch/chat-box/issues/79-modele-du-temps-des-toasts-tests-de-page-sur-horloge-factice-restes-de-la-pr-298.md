# 79: Modèle du temps des toasts : les tests de page sur horloge factice qui attendent un toast, depuis la file de la PR 298

**What to build:** Depuis la PR 298 (ticket 62), `say()` met les toasts en file : un toast attend son tour derrière ceux qui sont à l'écran (2,6 s, 7 s en rouge). Sur une horloge factice (`p.clock`, `reload_on_clock`, `stand_still`), le toast suivant ne paraît que si le test fait avancer l'horloge. Deux tests ont cassé à cause de cela (quatre de `test_page_writing.py` en CI, puis `test_a_reply_given_up_that_the_hub_took_after_all_goes_from_the_page_and_the_store[as it comes]`, rouge 6/6 sur t-compute avant `d4a58a9`) ; d'autres peuvent passer par chance. Aujourd'hui `toasted()` attend 20 s au lieu de 8 (`tests/page/pagehelp.py`), ce qui cache un toast tardif.

Fichiers suspects (horloge factice et attente d'un toast, nombre d'emplois d'horloge / de lecture du toast) :
- `tests/page/test_page_writing.py` : 34 / 57
- `tests/page/test_page_outage.py` : 33 / 12
- `tests/page/test_page_actions.py` : 87 / 14
- `tests/page/test_page_drafts.py` : 4 / 2

Deux assertions à revoir en particulier :
- `tests/page/test_page_writing.py:4709-4711` : `assert toast(p) == ""` (« said once for this save ») passe tant que le premier toast « Saving… » est encore à l'écran : un second `say()` attendrait en file et n'aurait pas paru. Si la garde `refusedSaid` cédait, le test resterait vert.
- `tests/page/test_page_drafts.py:176` : `"while you wrote" not in toast(page)` passe si ce toast est encore en file.

À faire :
- Lire la file au lieu de deviner : un crochet de test (ou une fonction de `pagehelp`) qui fait avancer l'horloge jusqu'à ce que le toast attendu paraisse, ou qui dit que la file est vide (« aucun toast ne viendra »).
- Remettre `toasted()` à 8 s par défaut ; 20 s seulement là où un toast attend derrière un toast rouge.
- Pour chaque fichier suspect : lister les tests qui attendent un toast sur horloge factice, montrer celui qui échoue sur t-compute avec une file chargée (jamais sur le portable), corriger.
- Corriger le commentaire de `tests/page/test_page_writing.py:2683` : il dit que l'horloge est arrêtée, mais `given_up` appelle `reload_on_clock(p)` sans pause (`pagehelp.py:304`), donc l'horloge court au pas réel.

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** `tests/page/test_page_writing.py:4709-4711`, puis `tests/page/test_page_drafts.py:176`, puis `test_page_outage.py`.

- [ ] Chaque test de page qui attend un toast sur horloge factice le fait en faisant avancer l'horloge, pas par chance
- [ ] Les deux assertions « pas de toast » échouent si le second toast est dit
- [ ] `toasted()` revient à 8 s par défaut
