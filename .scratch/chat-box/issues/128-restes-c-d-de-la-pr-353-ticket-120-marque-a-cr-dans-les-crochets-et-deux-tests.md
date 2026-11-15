# 128: Restes c et d de la PR 353 (ticket 120) : marque à CR dans les crochets, docstring et test d'élément vide

**What to build:** Restes de la revue Opus de la PR 353, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-120-reviews/opus-1.md`, verdict GO sur b90b6a0 après la correction de b1. Aucun ne produit une écriture fausse : le contrôle du nombre de cases et le rendu du résultat refusent le cas.
1. **c1.** `task_marks` trouve une marque à `1. [ \r] d` (un CR entre le caractère d'état et `]`), là où pandoc ne dessine pas de case. Une coche de ce bloc passe par le chemin général, sans écriture fausse. Décider : ne pas lire la marque (comme pandoc), ou la garder et l'écrire en SPEC.
2. **d.** La docstring de `task_marks` (« a CR anywhere in a line neither hides a mark nor makes one pandoc does not draw ») est fausse pour un CR dans les crochets. La corriger avec le point 1.
3. **d.** `test_an_empty_task_item_next_to_a_box_never_takes_its_tick` n'est plus vide mais passe encore sur le code d'avant la PR 347 : le contrôle du nombre de cases refuse d'abord. Ajouter un cas que seul le rendu du résultat attrape, ou le dire dans le test.
4. **d.** L'assistant `_page_with_box_flipped` des tests passe par le cache de `_rendered` : inoffensif, à noter ou à vider dans le test.

**Blocked by:** PR 353 fusionnée

**Claimed by:** Dalia

**Status:** done (PR 360, merged 536f709)

- [x] points 1 et 2 corrigés ou écartés avec la preuve ; 3 et 4 faits
