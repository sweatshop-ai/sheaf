# 145: Restes c de la PR 374 (ticket 140) : la branche positive de `_goes_on` sans test, et des formes que la lecture par le texte devine mal

**What to build:** Les constats de classe c de la revue Opus 1 de la PR 374 (ticket 140, merge 4a6e237), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-140-reviews/opus-1.md` (c1, c2, c3). Aucun a ni b. Aucun ticket ne les portait (trouvé par l'audit de Birgit, 2026-11-15). Les tests tournent sur le serveur auto-hébergé, jamais sur le portable.

1. **c2 d'abord : un test qui passe par la branche positive de `_goes_on`** (`src/sheafmd/edit.py`). Avec `_goes_on` forcé à `False`, les 184 tests ciblés de la revue passaient : seul le cas `- [ ]\n  continued` (une marque vide avec une ligne indentée dessous, que pandoc dessine comme une case) dépend de la branche, et sans elle il retombe sur les rendus en log n. **À vérifier avant d'écrire quoi que ce soit :** la PR 374 a ajouté `test_ticked_html_in_a_long_list_with_empty_items_and_a_continued_item_costs_a_fixed_number_of_renders` (`tests/test_hub_list.py`, CRLF et LF, 200 et 800 éléments), dont la liste commence par `- [ ]`, `- [ ] `, `  continued`. Forcer `_goes_on` à `False` et lancer ce test sur le serveur auto-hébergé : s'il devient rouge, la case est déjà couverte, le dire avec la preuve et passer au point 2 ; sinon, écrire un test dont l'entrée est une longue liste d'éléments `- [ ]\n  more`, qui coche une case après l'un d'eux et affirme le même nombre de rendus à 200 et à 800 (au plus 3). Il doit être rouge quand `_goes_on` est forcé à `False`.
2. **c1 : pour chacune des formes de la revue, un test qui prouve que le repli lent rend juste** (la lecture devinée est refusée, `_boxed_marks` sert, la bonne case est cochée, rien d'autre ne change) :
   - `- [ ] \xa0` (espace insécable après la marque) : devinée « sans case », pandoc dessine une case (`str.strip()` retire U+00A0) ;
   - `> - [ ]\n>   more` (continuation citée) : devinée « sans case », pandoc dessine une case (`_goes_on` mesure l'indentation avant le `>`) ;
   - `- [ ]\n  - [ ] c` (parent vide avec une sous-liste) : devinée « case », pandoc n'en dessine pas.
   Les autres formes du tableau de la revue (`# h`, fence, code indenté sous la marque, `- [ ] <!-- c -->`, une ligne paresseuse d'une seule espace) peuvent suivre le même chemin dans la même fonction paramétrée. **Corriger la lecture devinée seulement si l'un de ces tests rend faux** (une case fausse cochée, ou une écriture refusée à tort) ; sinon, écrire dans ce ticket que le repli est juste et ne rien changer à `_drawing_marks`. La perte de vitesse sur les longues listes qui contiennent une de ces formes est connue (retour au log n rendus, 17 s à 4 100 éléments) : le dire dans la docstring de `_drawing_marks`, qui dit trop (« never as a box »), sans la rendre plus lisible que le code.
3. **c3 :** déjà fait dans la PR 374 (un appel à `ticked_html` et une variante CRLF dans le test cité au point 1) ; vérifier et cocher.

**Blocked by:** none

**Claimed by:** Bruno

**Status:** done (PR 378, merged as 8ccd2dc)

**Par où commencer :** `tests/test_hub_list.py`, à côté de `test_a_tick_in_a_long_task_list_with_an_empty_item_costs_a_fixed_number_of_renders`. Sur le serveur auto-hébergé : forcer `_goes_on` à `False` et voir quels tests virent au rouge.

- [x] c2 : un test passe par la branche positive de `_goes_on` et devient rouge quand elle est forcée à `False` (ou la preuve que `test_ticked_html_in_a_long_list_with_empty_items_and_a_continued_item_costs_a_fixed_number_of_renders` l'est déjà)
  - Preuve : `_goes_on` forcé à `False` sur le serveur auto-hébergé, ce test devient rouge en LF et en CRLF (`assert 10 == 12`). Aucun test ajouté.
- [x] c1 : un test par forme nommée prouve que le repli lent rend juste ; la lecture devinée n'est changée que si l'un d'eux est rouge
  - Preuve : `test_a_tick_in_a_list_the_text_reading_guesses_wrong_still_lands_on_the_right_line`, 8 formes, tous verts (le repli est juste), `_drawing_marks` inchangée ; `tests/test_hub_list.py` : 253 passed sur le serveur auto-hébergé. Les formes NBSP et citation sont servies par la première lecture, sans passer par `_boxed_marks` (dit dans le test).
- [x] c3 vérifié, docstring de `_drawing_marks` corrigée
  - Preuve : c3 est dans le test du point 1 (appel à `ticked_html`, CRLF) ; la docstring liste les formes, le repli et son coût (17 s à 4 100 éléments).
