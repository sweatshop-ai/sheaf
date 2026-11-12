# 37: Le `Timer` de `_call` (dictée) peut encore être dans `cut()` quand `_call` rend la main

**What to build:** Dans `src/sheafmd/hub/transcribe.py`, `finally` fait `timer.cancel()` puis `conn.close()`. `cancel()` n'attend pas un rappel déjà commencé : si le délai tombe au moment où une réponse complète vient d'être lue, `_call` peut rendre `(status, data)` pendant que `cut()` est encore dans `shutdown`. Le fil ne garde ni la clé, ni les en-têtes, ni le corps et ne peut plus rien lire, donc ce n'est pas une fuite ; mais « rien ne tourne » du docstring est trop fort. Classe : c (tour 3 de Codex, GO).

**Blocked by:** aucun

**Établi (preuves) :** `codex-round3.md` de pr-06b-reviews. Non reproduit.

**Par où commencer :** après `cancel()`, `join()` le timer (il ne dure que le temps d'un `shutdown`), ou corriger le docstring.

- [ ] Le docstring de `_call` dit ce qui est vrai
- [ ] Si `join` est ajouté : un test où le rappel est lent montre que `_call` ne rend la main qu'après lui
