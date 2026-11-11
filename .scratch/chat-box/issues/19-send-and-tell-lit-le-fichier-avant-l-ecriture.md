# 19: Le test « envoyer et Tell » lit le fichier avant d'y trouver la réponse, de temps en temps en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_writing.py::test_send_and_tell_starts_one_tell_and_the_thread_waits_for_its_reply`.

**Blocked by:**
- 04

**Claimed by:** Birgit 2026-11-11 12:58

**Status:** in-progress

`assert [] == ['and plums?']` : `.rd-pending-tell` est là mais le fichier n'a pas encore la réponse. Dans la page, `telling[id]` n'est posé qu'à la réponse du hub (`started`) ou par un instantané du flux (`takeTelling`, ligne 357) ; laquelle des deux a dessiné la ligne n'est pas établi. PR #240 run 42923857640 tentative 1. Cause non prouvée, non reproduite en local. À faire : au timeout, dire ce que le fichier et la boîte contenaient et quelle requête avait été répondue.

- [x] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [x] Le correctif traite la cause, pas un délai ou une relance

**Cause (reproduite en local avec le message de la CI, 2026-11-11).** Défaut du test. La fixture `thread` fait son premier commentaire avec le bouton Tell (le seul bouton d'envoi quand un agent est là), donc `.rd-pending-tell` est déjà sur la page avant que la réponse parte : `wait_for_selector` rend la main aussitôt, et `replies(file)` est lu avant que le hub ait écrit la réponse. Mesuré : `PENDING BEFORE THE REPLY: 1`, `REPLIES BEFORE: []`. Reproduit à la demande : `/_/comment` retenu 800 ms donne `assert [] == ['and plums?']`, le message de la CI. Ni `started` ni `takeTelling` n'y sont pour rien.

**Correctif.** Le test attend la réponse dans le fichier (`until(replies == …)`), ce que le test vérifie, puis la ligne. Rouge avec l'ancienne attente et 800 ms de retard, vert avec la nouvelle.

- [ ] CI verte sur trois passages de suite
