# 25: Le test « réponse à un fil supprimé revenue dans la boîte d'un nouveau commentaire » dort 300 ms au lieu d'attendre

**What to build:** Remplacer l'attente fixe de 300 ms de `tests/page/test_page_writing.py::test_a_reply_to_a_deleted_thread_that_came_back_into_a_new_comments_popover_stays_when_the_comment_is_taken` par une attente de ce que le test vérifie (le premier champ de la boîte contient la réponse « words for a gone thread »), pour qu'une machine chargée ne le fasse pas échouer.

**Blocked by:** 04

**Claimed by:** Elif 2026-11-12 12:55

**Status:** in-progress

**Ce qui ne va pas (une lecture, pas une preuve) :** PR #245, run 43199291471 (tête a7e4127), tentative 1 : `1 failed, 984 passed`, échec à `test_page_writing.py:3361` : `assert p.input_value("#rd-popover textarea") == "words for a gone thread"` rend `'about the pears'`. La relance du même run (tentative 2) est verte. Sur main 2883104 le test avait passé (run 43198417261). En local, le test passe 26 fois sur 26 sur la tête de la PR 245 et 23 fois sur 23 sur main 2883104 (Chromium seul : le test n'utilise que la fixture `thread`), dont 12 en parallèle sur machine à charge 65. Le test attend que « about the pears » sorte du stockage (`draftsReplace(own)` s'exécute juste après le retour du post), puis dort 300 ms avant de lire le champ ; le redessin de la boîte vient après l'écriture du stockage, donc sur un coureur chargé (ce job a duré 1085 s) 300 ms peuvent ne pas suffire. Les changements des tickets 14 à 16 ne touchent pas cette voie (le stash ne tourne qu'à la fermeture de la boîte).

- [ ] Une attente de l'état attendu (le premier champ lit la réponse) remplace le `wait_for_timeout(300)`, avec le message de l'attente qui dit ce qui a été vu
- [ ] Le test passe 10 fois de suite en local, une fois avec la boîte ralentie (par exemple un délai sur la réponse du hub), sans jamais dormir un temps fixe
- [ ] Si l'échec se reproduit une fois l'attente corrigée, la cause est cherchée dans le code (le redessin après l'envoi), pas dans le test
- [ ] CI verte
