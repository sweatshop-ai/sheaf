# 19: Le test « envoyer et Tell » lit le fichier avant d'y trouver la réponse, de temps en temps en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_writing.py::test_send_and_tell_starts_one_tell_and_the_thread_waits_for_its_reply`.

**Blocked by:**
- 04

**Claimed by:** Birgit 2026-11-11 12:58

**Status:** in-progress

`assert [] == ['and plums?']` : `.rd-pending-tell` est là mais le fichier n'a pas encore la réponse. Dans la page, `telling[id]` n'est posé qu'à la réponse du hub (`started`) ou par un instantané du flux (`takeTelling`, ligne 357) ; laquelle des deux a dessiné la ligne n'est pas établi. PR #240 run 42923857640 tentative 1. Cause non prouvée, non reproduite en local. À faire : au timeout, dire ce que le fichier et la boîte contenaient et quelle requête avait été répondue.

- [ ] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [ ] Le correctif traite la cause, pas un délai ou une relance
- [ ] CI verte sur trois passages de suite
