# 81: Restes de la PR 302 (ticket 60) : disque qui refuse d'écrire, verrou global à chaque annonce, thunk qui lève, tests, passage Codex dû

**What to build:** Les restes (classe c et d) des deux revues Opus de la PR 302 (ticket 60, GO), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-60-reviews/opus-round1.md` et `opus-round2-narrow.md`, et `handoff-Salma-2026-11-14.md`. Rien de ceci ne bloque ; chaque point est corrigé avec un test rouge ou écarté avec la raison.
1. **(c, tour 2) Un disque qui refuse d'écrire fait maintenant échouer un listing qui ne trouve que des lignes révoquées** (`waiting.py`, `take`, `save = len(rows) != n`) : `documents` lève l'`OSError`, comme `sweep` et une marque `seen` le faisaient déjà ; avant la PR, le listing répondait sans écrire. Décider : garder (SPEC 9.8 le dit) ou tolérer comme l'écriture des seuls noms.
2. **(d, tour 2) Le test `test_a_listing_that_only_finds_a_revoked_row_writes_its_end_...` ne liste pas deux fois** : il prouve « écrit, puis pas renvoyé » par un `sweep`, pas par un second listing. Le contrôle du fichier suffit à fixer le correctif ; ajouter le second listing.
3. **(c, tour 1) Un thunk tenu qui lève abandonne le reste des événements et des lignes du journal après l'écriture** (`waiting.py`, boucle `for go in held`). Aucun cas en production (`Bus.publish` et `diagnostics.record` ne lèvent pas) ; il faudrait un `record` remplacé ou futur.
4. **(c, tour 1) `_publish_telling` tient `Waiting._lock` (global) pendant `session_to()` et la diffusion, à chaque `changed` de chaque document** (`live.py`) : une écriture lente dans `_change` (fsync) retarde les annonces de tous les documents. Existait par `agent_tells`, la portée grandit. De la contention, pas un défaut de justesse ; mesurer avant de toucher.
5. **(d, tour 1) `test_a_changed_event_is_read_under_the_tells_lock_...` peut passer au vert sans le correctif sous charge** (`taker.join(0.5)`) ; jamais au rouge à tort. Déterministe avec le correctif ; à rendre déterministe (attendre que le taker soit bloqué sur le verrou, pas un délai).
6. **F3 et F6 du ticket 60** : corrigés dans la PR 302 (F3 : `waits` remplit les anciennes lignes dans la réponse ; F6 : le 409 nomme l'agent gardé par la ligne), donc rien à reprendre.

**Passage Codex dû :** Codex n'a pas pu tourner sur la PR 302 (plus de jetons jusqu'à 15 h le 2026-11-14) ; les deux revues sont d'Opus. Faire tourner `/codex-review --base` sur le diff de la PR 302 (merge 37c99b1) ; ses trouvailles deviennent des tickets, pas un retour en arrière.

**Blocked by:** none

**Claimed by:** Gudrun

**Status:** done (la PR 308 est fusionnée 7c69ad8 ; le passage Codex sur la PR 302 continue dans le ticket 82, point 8)

- [x] Chaque point est soit corrigé avec un test rouge, soit écarté avec la raison (PR 308, fusionnée 7c69ad8 ; preuves ci-dessous ; restes c/d : ticket 88)
- [ ] Le passage Codex sur le diff de la PR 302 est fait, ses trouvailles classées (déplacé au point 8 du ticket 82, après 20 h)

## Gudrun, 2026-11-14 (PR 308, branch chat-box/81)

1. **Gardé.** SPEC 9.8 dit qu'un disque qui refuse d'écrire fait échouer la passe ; `sweep` et une marque `seen` le faisaient déjà. Un test l'épingle pour un listing (`..._fails_on_a_disk_that_refuses_writes_as_a_sweep_does`).
2. **Corrigé** : le test liste deux fois.
3. **Corrigé, test d'abord** (rouge : 1 événement au lieu de 2) : `_change` exécute tous les thunks tenus, puis lève la première erreur.
4. **Mesuré, rien changé.** `_change` tient le verrou 0,23 ms en médiane (max 0,38 ms, fsync compris, 300 passes) ; une annonce d'un autre document sous écritures continues : p95 1,2 ms, max 1,5 ms (seule : 0,04 ms). Pas de retard réel.
5. **Corrigé** : le test attend que le taker soit bloqué sur le verrou (un verrou qui signale un acquire non bloquant refusé), plus de délai. Rouge sans le verrou, 3 fois sur 3.
6. Rien à reprendre (F3, F6).

**Passage Codex sur le diff de la PR 302 (merge 37c99b1) : case laissée ouverte.** Codex est à sa limite d'usage jusqu'à 20 h le 2026-11-14 ; le passage est reporté après 20 h.
