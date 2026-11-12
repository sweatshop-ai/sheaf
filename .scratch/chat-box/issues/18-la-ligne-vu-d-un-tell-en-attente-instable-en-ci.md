# 18: La ligne « vu » d'un Tell en attente n'arrive pas, de temps en temps, en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_waiting_tell.py::test_tell_waits_then_is_seen_and_the_line_survives_a_reload`.

**Blocked by:**
- 04

**Claimed by:** Elif 2026-11-12 10:01

**Status:** in-progress

L'attente de la ligne « has seen it » expire. PR #240 run 42923857640 tentative 1. Pas l'attente d'Échap : aucun envoi n'est abandonné. Cause non prouvée, non reproduite en local. À faire : un diagnostic au timeout (lignes vues, texte de la boîte, état `waits` de la page), puis lire le prochain rouge.

- [ ] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [ ] Le correctif traite la cause, pas un délai ou une relance
- [ ] CI verte sur trois passages de suite
