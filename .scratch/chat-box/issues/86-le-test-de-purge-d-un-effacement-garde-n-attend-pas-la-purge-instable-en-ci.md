# 86: Le test d'un effacement gardé que le stockage plein ne peut pas écrire attend en vain la purge : instable en CI, une fois

**What to build:** Trouver la cause d'un échec CI intermittent et corriger le test, de la famille des tickets 20 et 61. Test : `tests/page/test_page_chat_box.py::test_a_held_clear_that_the_full_store_cannot_write_is_tried_by_the_reads_only_not_by_the_redraws_it_queues`, ligne 1023 : `until(lambda: p.evaluate("window.__refusedSets || 0") > 0, what="the purge to meet the full store")` expire (`AssertionError: timed out waiting for the purge to meet the full store`, `pagehelp.py:184`). Classe : c (un test, pas la page : à confirmer par la cause). Les tickets 50, 51 et 59 ont écrit ce test (commits df351f7, 0d8af52) ; 59 F7 traite déjà les tests sans attente fixe, ce ticket-ci est un échec précis.

**Blocked by:** none

**Claimed by:** Oskar

**Status:** done (PR 316, merged as 5738035)

**Établi (preuves) :** vu une fois, PR 306, sur 08f0833 (la PR ne touche pas ce fichier), tranche 2/3, rouge aux deux tentatives du job (13:27 et 13:32 UTC), vert au rejeu des jobs échoués. Run 43599394576, job 132460763250 : https://github.com/sweatshop-ai/sheaf/actions/runs/43599394576/job/132460763250. Dans la même exécution, la tranche 1/3 a échoué sur un autre test (ticket 79). Cause non établie.

**Par où commencer :** lire les tickets 50, 51, 59 (F7) et 61 (méthode : reproduction sous charge sur un runner, branche jetable) ; lancer le test en boucle sur le serveur auto-hébergé (jamais sur le portable), machine chargée ; chercher ce qui doit déclencher la purge (`window.__refusedSets`) avant l'attente de la ligne 1023 et ce qui peut la rater.

- [x] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [x] Le correctif traite la cause, pas un délai ni une relance
- [x] CI verte sur trois passages de suite
