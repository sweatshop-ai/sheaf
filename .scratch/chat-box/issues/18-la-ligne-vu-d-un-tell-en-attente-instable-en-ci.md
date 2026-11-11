# 18: La ligne « vu » d'un Tell en attente n'arrive pas, de temps en temps, en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_waiting_tell.py::test_tell_waits_then_is_seen_and_the_line_survives_a_reload`.

**Blocked by:**
- 04

**Claimed by:** Birgit 2026-11-11 12:58

**Status:** in-progress

L'attente de la ligne « has seen it » expire. PR #240 run 42923857640 tentative 1. Pas l'attente d'Échap : aucun envoi n'est abandonné. Cause non prouvée, non reproduite en local. À faire : un diagnostic au timeout (lignes vues, texte de la boîte, état `waits` de la page), puis lire le prochain rouge.

- [x] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [x] Le correctif traite la cause, pas un délai ou une relance

**Cause (preuve, 2026-11-11).** La réponse à l'envoi (et `applyComments`) porte les Tells tels que le hub les avait en l'écrivant : `queued`. L'événement « l'agent l'a vu » (`seen`) arrive par le flux, et une réponse lente peut le dépasser ; `takeTelling` remplaçait alors `waits` par `queued` et la ligne « has seen it » repartait en « Waiting for… » pour de bon. Reproduit à la demande : la réponse de `/_/comment` retenue 1,5 s, `documents` appelé pendant ce temps ; la ligne « seen » s'affiche puis revient à « Waiting » (rouge sans correctif, vert avec). Sur un runner chargé l'ordre des deux arrivées peut s'inverser de même.

**Correctif.** `takeTelling` ne ramène pas un Tell `seen` à `queued` (`page.js`). Test : `test_a_send_answered_after_the_agent_saw_it_does_not_take_the_seen_line_back`.

- [ ] CI verte sur trois passages de suite
