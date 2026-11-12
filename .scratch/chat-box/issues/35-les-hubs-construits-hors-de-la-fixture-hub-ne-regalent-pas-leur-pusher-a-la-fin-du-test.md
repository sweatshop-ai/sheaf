# 35: Les hubs construits hors de la fixture `hub` ne règlent pas leur pusher à la fin du test, et une ligne `push-failed` peut tomber dans le test suivant

**What to build:** le ticket 32 (PR #252) a trouvé la cause du `too many values to unpack` à `tests/test_hub_commits.py:169` : le fil `sheaf-push` d'un hub survit à son test, et sa ligne `push-failed` est écrite dans l'état du test suivant (`diagnostics.record` lit le dossier d'état dans l'environnement à l'appel). La fixture `hub` de `tests/conftest.py` appelle maintenant `commits.settle(30)` à la fin du test. Les hubs construits ailleurs ne le font pas : `tests/two_roots.py:58` (`TwoRoots.hub()`, dépôts `commit = true, push = true`), `tests/page/conftest.py:43`, la fixture locale `hub` de `tests/test_hub_tell.py:76` et les appels directs à `Hub(...)`. Exemple relevé par le bug hunt de la PR #252 : `tests/test_private_root_closed.py::test_unreadable_private_root_fails_closed` finit sur un `comment(...)` qui écrit, sans `settle()` ; son push court dans le test suivant.

**Blocked by:** 32 (PR #252 fusionnée)

**Classe :** c/d (test seulement, instable potentiel ; aucun test ne fait échouer un push sur ces hubs aujourd'hui, les pushs atteignent un dépôt distant existant et n'écrivent aucune ligne).

**Établi (preuves) :** PR #252, trace sur t-compute, 7 968 tests hors navigateur : 25 lignes écrites par le hub d'un test antérieur. Le bug hunt Opus (`~/.claude/pm/chat-box-handoffs/pr-32-reviews/codex-1.md`) a lu les autres constructeurs de hub : aucun ne fait échouer un push aujourd'hui.

**Par où commencer :** régler tout hub à la fin du test depuis un seul endroit, pas fixture par fixture : par exemple une fixture autouse qui enregistre chaque `Hub` construit (enveloppe de `Hub.__init__`) et appelle `commits.settle` avant que `sheaf_env` ne soit défait. Attention : l'ordre de démontage (le réglage doit avoir lieu tant que l'environnement du test est encore en place) et les hubs que le test arrête lui-même (`stop_jobs`, le pusher se termine par `Stopped`).

- [x] Tout hub construit dans un test est réglé à la fin de ce test, d'un seul endroit
- [x] Un test pose le cas à la main (un hub hors fixture `hub` avec un push échoué en cours à la fin du test) et échoue sans le correctif
- [x] La fixture `hub` de `tests/conftest.py` n'a plus besoin de son propre `settle` (ou le garde, s'il reste plus simple), sans perdre le test de `tests/test_hub_pusher_settles.py`
- [x] CI verte sur deux passages de suite

**Claimed by:** Isolde 2026-11-12 18:45

**Status:** in-progress — PR 256 open, waiting for merge (head 71d94b7, CI run 43274033495 attempts 1 and 2 both 3/3 green; reviews in ~/.claude/pm/chat-box-handoffs/pr-35-reviews/: Opus fallback GO, standards clean, spec no blocker). Done with the merge sha.
