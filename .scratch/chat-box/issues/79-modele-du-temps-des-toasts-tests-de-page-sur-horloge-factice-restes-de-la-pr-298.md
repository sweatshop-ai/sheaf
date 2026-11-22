# 79: Modèle du temps des toasts : les tests de page sur horloge factice qui attendent un toast, depuis la file de la PR 298

**What to build:** Depuis la PR 298 (ticket 62), `say()` met les toasts en file : un toast attend son tour derrière ceux qui sont à l'écran (2,6 s, 7 s en rouge). Sur une horloge factice (`p.clock`, `reload_on_clock`, `stand_still`), le toast suivant ne paraît que si le test fait avancer l'horloge. Deux tests ont cassé à cause de cela (quatre de `test_page_writing.py` en CI, puis `test_a_reply_given_up_that_the_hub_took_after_all_goes_from_the_page_and_the_store[as it comes]`, rouge 6/6 sur le serveur auto-hébergé avant `d4a58a9`) ; d'autres peuvent passer par chance. Aujourd'hui `toasted()` attend 20 s au lieu de 8 (`tests/page/pagehelp.py`), ce qui cache un toast tardif.

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
- Pour chaque fichier suspect : lister les tests qui attendent un toast sur horloge factice, montrer celui qui échoue sur le serveur auto-hébergé avec une file chargée (jamais sur le portable), corriger.
- Corriger le commentaire de `tests/page/test_page_writing.py:2683` : il dit que l'horloge est arrêtée, mais `given_up` appelle `reload_on_clock(p)` sans pause (`pagehelp.py:304`), donc l'horloge court au pas réel.

**Blocked by:** none

**Claimed by:** Isolde

**Status:** done (PR 317, merge 2911952)

**Par où commencer :** `tests/page/test_page_writing.py:4709-4711`, puis `tests/page/test_page_drafts.py:176`, puis `test_page_outage.py`.

- [x] Chaque test de page qui attend un toast sur horloge factice le fait en faisant avancer l'horloge, pas par chance
- [x] Les deux assertions « pas de toast » échouent si le second toast est dit
- [x] `toasted()` revient à 8 s par défaut
- [x] Le test send-again passe par l'avance de l'horloge, pas par l'attente (fait) ; qu'il échoue encore en CI faute de l'événement `changed` du hub (aucun toast après « did not go out ») est déplacé au ticket 100

**Vu en CI, 2026-11-14 (PR 306, sur 08f0833, sans lien avec la PR : elle ne touche pas ce fichier) :** `tests/page/test_page_writing.py::test_a_send_again_that_fails_to_reach_the_hub_does_not_hide_that_the_send_before_it_was_taken`, ligne 2858 (`toasted(p, TAKEN)`, « What you sent reached the hub after all »), `AssertionError: timed out waiting for a toast saying ...` (`pagehelp.py:184`), tranche 1/3, rouge aux deux tentatives du job (13:32 et 13:33 UTC), vert au rejeu des jobs échoués. Run 43599394576, job 132460763370 : https://github.com/sweatshop-ai/sheaf/actions/runs/43599394576/job/132460763370. Même famille que ce ticket : le test appelle `given_up` (horloge qui court au pas réel, `reload_on_clock` sans pause), dit d'abord le toast rouge « did not go out » (7 s à l'écran), puis attend `TAKEN`, qui est derrière lui dans la file ; `toasted()` attend 20 s. Cause non vérifiée : à établir sur le serveur auto-hébergé avec une file chargée, comme le demande ce ticket. Case à ajouter : ce test passe par l'avance de l'horloge, pas par l'attente.
