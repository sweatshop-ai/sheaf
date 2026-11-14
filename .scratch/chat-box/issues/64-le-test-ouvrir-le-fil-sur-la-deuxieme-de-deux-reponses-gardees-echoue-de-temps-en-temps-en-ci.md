# 64: Le test « ouvrir le fil sur la deuxième de deux réponses gardées » échoue de temps en temps en CI

**What to build:** `tests/page/test_page_writing.py::test_open_the_thread_on_the_second_of_two_kept_replies_draws_that_reply` a échoué une fois sur la tête 49be5dc de la PR 280 (job 132246003022, run 43530290138 tentative 1, tranche 3/3) et est passé à la deuxième tentative sans changement de code. Assertion : `sorted(texts) == ["words from page A", "words from page B"]`, reçu `["words from page B"]` : la réponse gardée de la page A manque dans la liste « not sent » après `come_back(thread)`. Le test envoie deux réponses depuis deux pages, fait échouer la première (500) et la seconde (`fail_the_send`), puis revient ; la liste vient du stockage partagé des deux pages. Cause non prouvée ; soupçon à vérifier : la lecture de la liste « not sent » arrive avant que l'écriture de la page A dans le stockage soit finie (le test n'attend pas l'écriture de A, seulement `unsent_line`). Aucun lien établi avec la PR 283 ni avec la PR 280. Classe : b (test instable ; peut-être un vrai ordre d'écriture de la page).

**Blocked by:** none

**Status:** ready-for-agent

**Établi (preuves) :** une défaillance sur 2 tentatives de 49be5dc ; aucune défaillance de ce test dans les logs des 16 derniers runs en échec sur les 100 derniers runs (43530281636, 43528478252, 43527615916, 43526211893, 43525374227, 43521980517, 43520149666, 43516866448, 43514478012, 43514300946, 43502942314, 43502870726, 43502440200, 43502218938, 43402531248, 43327923012). Non reproduit : les tests de page ne tournent pas sur le portable.

**À faire :** au timeout, dire ce que le stockage et la liste contenaient ; relancer le test 20 fois en CI sur main avant de conclure.

- [ ] Cause établie : test instable ou ordre d'écriture réel de la page
- [ ] Correctif avec un test rouge avant (ou le test attend l'écriture de A)
