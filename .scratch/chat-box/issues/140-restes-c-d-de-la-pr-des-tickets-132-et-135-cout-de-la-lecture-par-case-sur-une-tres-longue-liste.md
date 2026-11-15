# 140: Restes c et d de la PR des tickets 132 et 135 : coût de la lecture par case sur une très longue liste, et trous de test

**What to build:** Restes de la relecture Opus (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-132-reviews/opus-1.md`, `opus-2.md`). Aucun a ni b ne reste (b1 de opus-1 corrigé dans la PR).

**Classe c**
- c1 : à partir de 128 marques, les rendus par bit de `_boxed_marks` chassent le cache `_rendered` (8 entrées) : le rendu du bloc lui-même doit être refait, et les rendus des autres blocs de la même sauvegarde sont perdus. Borné.
- c2 : une très longue liste avec un élément vide paie environ log2(n) rendus complets à chaque case cochée (17 s à 4100 éléments, 0,7 s à 200) ; main allait droit à pandoc (et réécrivait la liste). Piste : garder la lecture par case par texte, comme `box_number`.

**Classe d**
- d1 : `test_a_tick_in_a_long_task_list_with_an_empty_item_costs_log_n_renders` tolère 16 rendus pour 10 mesurés ; resserrer.
- d2 : la garde `0 <= k` dans le filtre `sets` de `ticked_html` est redondante depuis la garde de bornes ; un `k` négatif rend maintenant None (avant, `found[-1]` marchait).
- d3 : docstring de `box_number` (« a chain the regex misses ») et de `_render_source` (la raison du cache de 8) périmées.

**Blocked by:** none (PR 371 fusionnée, cadd9d6)

**Claimed by:** Rumi 2026-11-15 14:55

**Status:** done (PR 374, merged as 4a6e237)

- [ ] c1 et c2 faits ou écartés avec la preuve ; d1 à d3 faits
