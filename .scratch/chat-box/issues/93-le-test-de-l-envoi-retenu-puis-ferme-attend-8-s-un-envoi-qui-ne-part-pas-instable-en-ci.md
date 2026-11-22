# 93: Le test « Échap ou clic dehors pendant l'envoi d'une réponse » n'a pas vu l'envoi partir en 8 s : instable en CI, vu une fois

**What to build:** Trouver la cause d'un échec CI intermittent et corriger le test (ou la page, si la cause est là). Test : `tests/page/test_page_writing.py::test_escape_or_a_click_outside_during_a_reply_or_edits_send_closes_the_popover_and_the_hub_takes_it[reply-Escape]`. L'échec est dans `send_held` (test_page_writing.py:150), avant tout Échap : `until(lambda: held or p.wait_for_timeout(20), what="the send to go out")` lève `AssertionError: timed out waiting for the send to go out` (`tests/page/pagehelp.py:184`, délai 8 s). Après `Control+Enter`, la requête `/_/comment` n'a pas atteint la route en 8 s.

**Blocked by:**
- External: the next CI failure of this test, now reported by the diagnostic merged for this ticket (PR 365, 3bdeaf6)

**Claimed by:** (libre)

**Status:** ready-for-agent

**Établi (preuves) :** vu une fois, PR 315 (ticket 74, ne touche que `copyblock.py` et ses tests), sur 8c1b152, tranche 3/3, tentative 1, 2026-11-14 16:41 UTC. Run 43616032386 : https://github.com/sweatshop-ai/sheaf/actions/runs/43616032386, job 132511239379 : https://github.com/sweatshop-ai/sheaf/actions/runs/43616032386/job/132511239379. Le job a échoué avec 1 échec, 353 passés (test de page, Chromium/Firefox/WebKit) ; le test a échoué deux fois dans la même exécution (rejeu interne du test, deux traces dans le log). Vert au rejeu du job (tentative 2, job 132514856389). Les tests unitaires du même job : 2844 passés.

**Pas le ticket 10 :** le ticket 10 traite `test_a_reply_or_edit_whose_send_fails_after_escape_or_a_click_outside_comes_back_with_its_text`, un autre test (l'échec y vient après Échap, et le correctif `fail_a_reply` n'est pas dans le chemin de celui-ci). Même famille de forme (une boîte lue avant que la page ait fini), cause non établie ici.

**À faire :** relire le log du job avant toute hypothèse (le test n'imprime pas l'état de la page à cet échec ; ajouter ce diagnostic si la cause n'est pas lisible), puis écrire la cause avec sa preuve.

- [ ] La cause est écrite dans ce ticket avec la preuve
- [ ] Le correctif traite cette cause, pas un délai ou une relance
- [ ] CI verte sur trois passages de suite

**Tentative de cause (Yara, 2026-11-15) : non établie.** Le log du job ne dit rien de la page. Non reproduit sur le serveur auto-hébergé : 384 passages du test seul (24 boucles en parallèle, jusqu'à 40 brûleurs de CPU) et 18 passages du fichier entier sous xdist à charge ~100, tous verts pour ce test (d'autres tests du fichier ont échoué à cette charge, pas celui-ci). Lu dans `page.js` : `go` n'envoie rien si le champ est vide, si `needClean()` dit « Save your edits first » ou « The document changed », ou si le fil a disparu ; `post` attend `ticking` (un tick de bouton, hors du chemin de ce test). Aucune de ces pistes n'a de preuve. PR 365 (diagnostic seul, tests) : au prochain échec le message dit si la page a rechargé (`same_load`), la valeur du champ, le popover et le toast.

**État après la PR du diagnostic (Yara, 2026-11-15) :** le diagnostic est fusionné (PR 365, merge 3bdeaf6) : `send_held` et `new_comment_held` passent par `wait_for_send`, qui dit en cas d'échec si la page a rechargé, la valeur du champ, le popover et le toast. Aucune des trois cases n'est cochée : la cause n'est pas établie (non reproduit, voir plus haut), donc pas de correctif ni de trois CI vertes sur un correctif. Le ticket attend le prochain échec de ce test, avec le message du diagnostic.
