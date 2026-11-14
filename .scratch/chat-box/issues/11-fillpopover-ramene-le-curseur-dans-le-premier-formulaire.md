# 11: fillPopover ramène le curseur dans le premier formulaire

**What to build:** Quand plusieurs formulaires sont ouverts, le curseur ne doit pas sauter vers le premier. Issu de la review du bug hunt de la PR #238 (P2 n° 5) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Claimed by:** Birgit 2026-11-11 00:19

**Status:** done

**Ce qui ne va pas :** `page.js:2052-2053`. `fillPopover` refocalise `forms[0]` dès qu'un formulaire avait le focus. Avec deux formulaires ouverts, le curseur peut sauter du second au premier pendant qu'on tape.

- [x] Avec deux formulaires ouverts, le focus reste dans celui où l'on tape après un appel à `fillPopover`
- [x] Test à deux formulaires, rouge avant le correctif
- [x] Avec un seul formulaire, comportement inchangé
- [x] PR séparée, CI verte (PR #241, tête 97a051c, run 43006211442 tentatives 1 et 2 réussies, fusion 7dae7b2)

**Preuve (2026-11-11):** `test_a_redraw_leaves_the_cursor_in_the_form_it_was_in` (deux formulaires, tests/page/test_page_chat_box.py), rouge avant le correctif (`document.activeElement` = BODY), vert après ; `test_a_redraw_leaves_the_cursor_in_the_only_form` (un seul formulaire) était rouge aussi avant. **Découverte :** le code d'origine calculait `writing` APRÈS `pop.innerHTML = …`, qui détache les formulaires et leur fait perdre le focus : `writing` était toujours faux, le `forms[0].focus()` de la review ne s'exécutait jamais et le curseur se perdait pour tous les formulaires (un seul compris). `fillPopover` lit maintenant le formulaire qui a le curseur (et la position du curseur) avant le redessin et le lui rend. Avec un seul formulaire, le curseur reste donc dans le champ au lieu de disparaître : c'est l'intention écrite dans le commentaire du code ; la case « comportement inchangé » est cochée sur cette lecture, à confirmer par Isolde. Fichier complet `test_page_chat_box.py` : 47 passés.

**Après la revue Opus (2026-11-11):** la position du curseur n'est relue que si le focus est dans un textarea (un bouton atteint par Tab n'a pas de `selectionStart`, le curseur sautait au début) : `test_a_redraw_keeps_the_caret_of_the_field_when_a_button_has_the_cursor`, rouge avant (`0 == 5`).
