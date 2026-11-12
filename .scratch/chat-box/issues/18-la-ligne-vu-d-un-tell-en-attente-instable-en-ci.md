# 18: La ligne « vu » d'un Tell en attente n'arrive pas, de temps en temps, en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_waiting_tell.py::test_tell_waits_then_is_seen_and_the_line_survives_a_reload`.

**Blocked by:**
- 04

**Claimed by:** Birgit 2026-11-11 12:58

**Status:** in-progress

L'attente de la ligne « has seen it » expire. PR #240 run 42923857640 tentative 1. Pas l'attente d'Échap : aucun envoi n'est abandonné. Cause non prouvée, non reproduite en local. À faire : un diagnostic au timeout (lignes vues, texte de la boîte, état `waits` de la page), puis lire le prochain rouge.

- [x] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [x] Le correctif traite la cause, pas un délai ou une relance

**Cause (reproduite en local, CI non confirmée, 2026-11-11).** La réponse à l'envoi (et `applyComments`) porte les Tells tels que le hub les avait en l'écrivant : `queued`. L'événement « l'agent l'a vu » (`seen`) arrive par le flux, et une réponse lente peut le dépasser ; `takeTelling` remplaçait alors `waits` par `queued` et la ligne « has seen it » repartait en « Waiting for… » pour de bon. Reproduit à la demande : la réponse de `/_/comment` retenue 1,5 s, `documents` appelé pendant ce temps ; la ligne « seen » s'affiche puis revient à « Waiting » (rouge sans correctif, vert avec). Que le rouge de PR #240 soit celui-là n'est pas confirmé par une CI : l'inversion de l'ordre des deux arrivées sur un runner chargé est l'hypothèse qui reste.

**Correctif.** `takeTelling` ne ramène pas un Tell `seen` à `queued` (`page.js`). Test : `test_a_send_answered_after_the_agent_saw_it_does_not_take_the_seen_line_back`.

**Revue Codex (P2).** Un fil peut attendre deux agents (cible changée après le premier Tell) : restaurer `seen` par identifiant de fil prêtait le « has seen it » du premier au Tell en attente du second. Reproduit (test `…is_not_lent_to_the_queued_tell_of_another_agent…`, l'événement `tell-queued` retenu pour que l'instantané arrive avant), corrigé : `seen` ne revient que pour le même agent (`to`).

- [x] CI verte sur trois passages de suite : runs 43190504226 sur 08c8883 et 43201969936 sur 4455590, chacun vert aux tentatives 1 et 2
