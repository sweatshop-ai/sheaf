# 88: Restes c/d de la PR 308 (ticket 81) : les erreurs autres que la première d'un changement, et des détails de test

**What to build:** Les restes de la revue Opus de la PR 308, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-81-reviews/opus-round1.md` (GO, pas de a ni b). Chaque point est corrigé ou écarté avec la raison.
1. **(c)** `Waiting._change` : seule la première exception d'un thunk tenu arrive à l'appelant, les autres ne sont ni jointes (`add_note`, `ExceptionGroup`) ni journalisées.
2. **(c)** Le passage `/codex-review --base` sur le diff de la PR 302 (merge 37c99b1) reste dû : il est suivi dans le ticket 81, case ouverte, à faire après 20 h le 2026-11-14.
3. **(d)** Le test du verrou des Tells garde une sortie par délai (5 s) : sans le correctif, un taker plus lent le rendrait vert à tort. Attendre `blocked.is_set() or not taker.is_alive()` sans limite.
4. **(d)** `failed = failed or e` dépend de la valeur de vérité de l'exception : `if failed is None`.
5. **(d)** Le docstring de `_change` ne dit pas qu'un thunk qui échoue n'arrête pas les autres.
6. **(d)** SPEC 9.8 point 3 ne dit pas que `documents` répond alors une erreur, ni qu'un événement ou une ligne qui échoue ne retient pas les autres.
7. **(d)** Dans le test du thunk qui lève, `bob` ne sert pas et `hub.record` est remis hors d'un `finally` (`monkeypatch.setattr`).

**Blocked by:** none

**Claimed by:** Marek

**Status:** ready-for-agent
