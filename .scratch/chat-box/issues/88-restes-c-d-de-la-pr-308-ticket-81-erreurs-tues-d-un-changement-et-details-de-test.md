# 88: Restes c/d de la PR 308 (ticket 81) : les erreurs autres que la première d'un changement, et des détails de test

**What to build:** Les restes de la revue Opus de la PR 308, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-81-reviews/opus-round1.md` (GO, pas de a ni b). Chaque point est corrigé ou écarté avec la raison.
1. [x] **(c)** `Waiting._change` : seule la première exception d'un thunk tenu arrive à l'appelant, les autres ne sont ni jointes (`add_note`, `ExceptionGroup`) ni journalisées.
   - Preuve : la première est relevée, les suivantes jointes par `add_note(repr(e))` (pas d'`ExceptionGroup` : les appelants attrapent `OSError`) ; test `test_the_other_errors_of_held_steps_ride_on_the_first_as_notes`, rouge avant le correctif (PR #310, merge 254edc3)
2. ~~**(c)** Le passage `/codex-review --base` sur le diff de la PR 302 (merge 37c99b1) reste dû : il est suivi dans le ticket 81, case ouverte, à faire après 20 h le 2026-11-14.~~ Écarté : doublon du point 8 du ticket 82, aucun travail ici.
3. [x] **(d)** Le test du verrou des Tells garde une sortie par délai (5 s) : sans le correctif, un taker plus lent le rendrait vert à tort. Attendre `blocked.is_set() or not taker.is_alive()` sans limite.
   - Preuve : la boucle sort sur `blocked.is_set() or sent.is_set()` (le premier `_send` de `waiting_tells`), car `not taker.is_alive()` pendait 300 s sans le verrou (revue Opus, classe b) ; sans le verrou le test échoue en 1,6 s, avec lui 70 passés (commit 561a95c)
4. [x] **(d)** `failed = failed or e` dépend de la valeur de vérité de l'exception : `if failed is None`.
   - Preuve : `waiting.py` `_change`, PR #310
5. [x] **(d)** Le docstring de `_change` ne dit pas qu'un thunk qui échoue n'arrête pas les autres.
   - Preuve : docstring de `_change`, PR #310
6. [x] **(d)** SPEC 9.8 point 3 ne dit pas que `documents` répond alors une erreur, ni qu'un événement ou une ligne qui échoue ne retient pas les autres.
   - Preuve : SPEC 9.8 point 3, PR #310 ; la revue Opus a vérifié par une sonde que `documents` répond `isError` quand `hub.record` lève
7. [x] **(d)** Dans le test du thunk qui lève, `bob` ne sert pas et `hub.record` est remis hors d'un `finally` (`monkeypatch.setattr`).
   - Preuve : `bob` retiré, `monkeypatch.setattr(browser.hub, "record", …)`, PR #310

**Blocked by:** none

**Claimed by:** Marek

**PR:** sweatshop-ai/sheaf#310, fusionnée en 254edc3 (tête 561a95c, CI 3/3 verte). Revue Opus : un b (corrigé), deux d acceptés : la note ne garde que `repr(e)`, sans trace (assez pour retrouver l'erreur dans `sheaf diag`, aucun thunk de production ne lève aujourd'hui) ; la SPEC dit « notes » (vocabulaire Python, mais le seul qui dit où l'erreur suivante se retrouve).

**Status:** done
