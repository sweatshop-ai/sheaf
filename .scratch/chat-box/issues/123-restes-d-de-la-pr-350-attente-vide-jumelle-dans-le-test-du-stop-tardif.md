# 123: Restes d de la PR 350 (tickets 117, 108) : la même attente vide dans le test jumeau

**What to build:** Revue Opus de la PR 350 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-117-reviews/review-1.md`), classe d, aucune de classe a, b ou c :
1. `tests/page/test_page_dictation.py` (autour de :428) : `test_the_stop_event_that_comes_late_leaves_the_new_recording_alone` garde le même `wait_for_timeout(300)` après le même `flush()` synchrone ; le retirer comme dans la PR 350. Les autres `wait_for_timeout(300)` du fichier sont à regarder un par un : seuls ceux qui suivent un `flush()` ou un événement synchrone n'attendent rien.
2. Sans cette attente, `assert hub.posts == []` ne contrôle qu'un instant ; sans gravité (l'assert `aria-pressed` attraperait la régression), rien à faire.
3. Le `clearTimeout` de `stopDictation` n'a pas de test propre : filet de sécurité, décision de la PR 350 maintenue (pas de test).

**Blocked by:** PR 350

**Claimed by:**

**Status:** ready-for-agent
