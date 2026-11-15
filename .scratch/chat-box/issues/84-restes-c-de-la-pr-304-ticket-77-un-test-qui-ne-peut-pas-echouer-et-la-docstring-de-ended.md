# 84: restes c de la PR 304 (ticket 77), un test de `restart` qui ne peut pas échouer et la docstring de `ended()`

**What to build:** Deux restes de la revue 1 de la PR 304 (classe c).
- c1 `tests/test_service.py:775` : même danger que le ticket 77, sous une forme qui n'échoue jamais. `command_hub` lance le hub comme enfant direct ; le `sheaf("restart")` du test tourne dans le processus du test, passe par `_make_room("upgrade")` puis `ended()` et reape cet enfant. `started.wait(timeout=30) == 0` est donc toujours vrai (ECHILD, Popen dit 0) et ne verrait pas une régression vers un code non nul. À faire : lancer le restart dans un sous-processus, ou lire le code de sortie par un autre chemin, et vérifier que le test échoue si le hub sort avec un code non nul.
- c2 `src/sheafmd/hub/client.py:317-322` : la docstring de `ended()` doit dire qu'un appelant qui attend lui-même ce pid perd le code de sortie à cause de ce reap.
- d (au passage) : `subprocess.run` du test du ticket 77 sans `timeout` ; sans effet réel (`STOP_WAIT` et pytest-timeout bornent).

Revue : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-77-reviews/review-1.md`.

**Blocked by:** none

**Claimed by:** Lennart

- [x] c1 le test de `restart` peut échouer : il lance `sheaf restart` dans un sous-processus (seam `linux` forcé par un `-c`) et un thread du test attend l'enfant. Preuve : avec `server.exit_code` qui rend 1 (temporaire, annulé), le nouveau test échoue `assert [1] == [0]`, l'ancien passait ; refait après le correctif de la classe b. Corps de la PR 306. Le d (timeout=120 du `subprocess.run` du test du ticket 77) est fait aussi.
- [x] c2 docstring de `ended()` : dit qu'un appelant qui attend lui-même ce pid perd le code de sortie à cause du reap (`src/sheafmd/hub/client.py`, PR 306).

**Status:** done (PR 306, merged as 4acd660). Revue Opus : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-84-reviews/review-1.md` (b corrigé dans la PR ; c et d au ticket 85). Deux tests rouges de la première CI notés aux tickets 79 et 86.
