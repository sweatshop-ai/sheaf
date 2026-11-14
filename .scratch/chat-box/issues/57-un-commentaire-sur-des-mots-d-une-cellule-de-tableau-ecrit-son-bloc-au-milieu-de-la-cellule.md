# 57: Un commentaire sur des mots d'une cellule de tableau écrit son bloc au milieu de la cellule

**What to build:** Même défaut que le ticket 55, dans un tableau : une sélection au milieu d'une cellule met le bloc dans les mots de la cellule (`| on<!-- sheaf-comment … -->e | two |`, vérifié avec pandoc gfm : la cellule est « on<!--…-->e »), donc un lecteur qui compare le texte d'une cellule le voit coupé. Le correctif du titre ne s'y applique pas tel quel : la fin de la **ligne** est après le `|` final, hors de toute cellule, et l'ancre du badge se lit par cellule. Le bloc doit aller à la fin de la **cellule**, avant son `|`, en comptant `\|` et le code en ligne. Classe : c (autres lecteurs du fichier, tableaux).

**Blocked by:** none

**Claimed by:** Amelie 2026-11-14

**Status:** done — on main via fd23dee (PR 288), les quatre cases ; les restes de classe c au ticket 68

**Par où commencer :** dans `comments.py`, la fonction qui donne le point d'ancre d'un bloc selon son type (`comment_point`, ticket 55) : ajouter le cas `table` (fin de la cellule qui contient la sélection, avant son `|`, `\|` et code en ligne compris), appelée aussi par `edit.py::_insert_comment`. Voir comment la lecture de l'ancre du badge se fait par cellule. Test d'abord.

- [x] Un commentaire sur un mot du milieu d'une cellule est écrit au bout de la cellule ; le texte de la cellule est entier, `quote` garde les mots choisis — preuve : tests unitaires de `add_comment`, rouges avant
- [x] Cellule avec `\|` et avec du code en ligne contenant `|` : le bloc va avant le vrai `|` de fin
- [x] `_insert_comment` remet un commentaire existant au bout de la cellule — preuve : test de `edit.py`
- [x] SPEC 10.4 dit la règle de la cellule
