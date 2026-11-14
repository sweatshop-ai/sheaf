# 85: Restes c/d de la PR 306 (ticket 84) : thread du test de `restart` en daemon et message d'échec

**What to build:** Revue Opus de la PR 306 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-84-reviews/review-1.md`. Le b (le sous-processus ne recevait pas le seam `linux`) est corrigé dans la PR. À reprendre, tous dans `tests/test_service.py`, test `test_restart_through_the_service_makes_room_for_a_hub_a_command_started` :
1. (c) ~l.777 : le thread `waiter` n'est pas un daemon ; si le hub ne sort jamais et que le teardown expire aussi, le thread bloqué dans `waitpid` empêche pytest de se terminer. `daemon=True`.
2. (d) ~l.785 : si `waiter.join(timeout=30)` expire, l'échec dit `assert [] == [0]`. Ajouter `assert not waiter.is_alive(), "the hub did not exit"` avant la vérification du code.

**Blocked by:** PR 306 mergée

**Claimed by:**

- [ ] Points 1 et 2 traités
- [ ] CI verte

**Status:** ready-for-agent
