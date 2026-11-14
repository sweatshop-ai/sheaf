# 89: Restes c/d de la PR 309 (ticket 85) : contexte du message d'échec et balayage des join sans is_alive

**What to build:** Revue Opus de la PR 309 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-85-reviews/review-1.md`. Optionnel, faible valeur :
1. (c2) `tests/test_service.py`, `test_restart_through_the_service_makes_room_for_a_hub_a_command_started` : le message `"the hub did not exit"` peut porter le contexte : `f"the hub (pid {started.pid}) did not exit within 30 s of the restart"`.
2. (hors périmètre) Même motif « join avec timeout puis assert sur une liste » sans `is_alive()` dans `tests/test_source.py:128,393`, `tests/test_hub_list.py:1208`, `tests/test_hub_upgrade.py:69`. Ces threads font du travail en processus, le risque de blocage de pytest est faible : à ne faire que si un balayage est voulu.

**Blocked by:** none

**Claimed by:** Tove

- [x] Point 1 traité (PR 313)
- [x] Point 2 : balayage fait (PR 313). Revue : c1 accepté (thread non démarré dans le cas « over »), c2 corrigé, c3 accepté ; d : test_hub_tell.py:1697 joint un `stopper` non démarré dans un finally, hors périmètre

**Status:** ready-for-agent
