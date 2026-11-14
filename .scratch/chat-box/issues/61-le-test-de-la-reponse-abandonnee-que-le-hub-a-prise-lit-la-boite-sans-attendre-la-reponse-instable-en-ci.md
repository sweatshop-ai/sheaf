# 61: Le test d'une réponse abandonnée que le hub a prise lit la boîte une seule fois, sans attendre que la réponse y soit : instable en CI, deux fois sur main

**What to build:** Trouver la cause d'un échec CI intermittent et corriger le test, de la famille du ticket 20 (cause trouvée pour un autre test, PR 244). Test : `tests/page/test_page_writing.py::test_a_reply_given_up_that_the_hub_took_after_all_goes_from_the_page_and_the_store`, ligne 2658 : `assert p.inner_text("#rd-popover").count(SLOW) == 1` donne `0 == 1`. Classe : c (un test, pas la page : à confirmer par la cause).

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Établi (preuves) :** vu deux fois sur main, même ligne, même message, chaque fois sur la tranche 2/3 :
- run 43525374227, job 132229691740, sur 4b62ad3 (fusion de la PR 278) ;
- run 43527634386, job 132237231935, sur 76284b4 (fusion de la PR 281).
La boîte montre « “apples” … Why apples? / Send reply » : le formulaire est parti et la réponse n'est pas dessinée. Ce n'est pas une régression de la PR 281 : la même ligne a échoué sur 4b62ad3, avant son code ; 3e1895f (4b62ad3 plus le code de la PR 281) était vert 3/3 ; les changements de page.js de la PR 281 (`pendingClears` dans `threadKeep` et `taken`, vidage dans `commentDraftsLoad`) n'agissent que quand le stockage refuse une lecture, et celui de ce test répond. Les tests voisins de ce fichier passent dans les mêmes jobs.

**Cause : non établie, hypothèse de lecture.** Le test affirme une seule fois, juste après `until(lambda: not typed(p))`, sans attendre que la réponse soit dessinée (un `inner_text` instantané, pas un `until`). Le symptôme est celui du ticket 20 : quand le flux dit `hello` pendant que l'envoi est dehors, `replayHeld` garde l'événement `changed` de l'écriture jusqu'à la réponse de `checkText` ou jusqu'à `CHECK_WAIT` (10 s, page.js ~3887) ; le ticket 20 a corrigé son test en avançant l'horloge de la page de cette durée. Ce test-ci ne le fait pas. À vérifier : reproduire à la demande sur t-compute (runner chargé, `hello` tardif) avant de choisir entre `until` sur le texte et avance de l'horloge.

**Première lecture d'Amaia, 2026-11-14 : HYPOTHÈSE, NON PROUVÉE.** Rien n'a été reproduit (t-compute hors service à 10:09 UTC). Dans ce test, `slow_hub.release()` libère le rendu du hub, qui publie alors l'événement `changed`. Si un `hello` tardif a fait lancer `checkText` à l'abandon (`replayHeld`), `heardAfterCheck` retient cet événement jusqu'à la réponse de la vérification ou `CHECK_WAIT` (10 s). `toasted(TAKEN)` passe (le toast part du gestionnaire de `changed`), mais l'assertion unique `inner_text(...).count(SLOW) == 1` s'exécute avant que la réponse soit dessinée. Ce serait la famille du ticket 20. À confirmer par une reproduction à la demande avant tout correctif. Worktree prêt : /home/tiroir/Projects/sheaf-wt/chat-box-61 (chat-box/61, depuis eb7b7ba).

**Par où commencer :** lire le ticket 20 (cause, correctif, test avec et sans `hello`) ; lancer le test en boucle sur t-compute (jamais sur le portable) avec la machine chargée ; mettre l'assertion de la ligne 2658 derrière un signal positif (`until` sur le texte de la réponse dans la boîte) ou avancer l'horloge de `CHECK_WAIT` comme le ticket 20, selon la cause trouvée.

- [ ] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [ ] Le correctif traite la cause, pas un délai ni une relance
- [ ] CI verte sur trois passages de suite

**À surveiller (pas de ticket tant que ça ne se répète pas) :** le run 43527634386, job 132237232321 (tranche 1/3), a 344 tests de page verts et 1 sauté : `tests/page/test_mount_allowlist.py:233`, « chromium cannot start here: BrowserType.launch: Target page, context or browser has been closed ». Le CI traite tout test sauté comme un échec (« page tests were skipped, so a browser did not start »). Une première observation, sur le runner, sans lien avec une PR.
