# 75: Tabulation après un marqueur de conteneur dans `projection`, et accents graves isolés dans un tableau cité, restes de la PR 296

**What to build:** Deux restes (classe b et c) de la revue Opus 2 de la PR 296 (ticket 68, GO), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-68-reviews/opus-2.md` et `handoff-Tomas-2026-11-14.md`. Tous deux existent déjà sur main.
1. **(b) Une tabulation après le marqueur d'un conteneur place le point 2 caractères trop loin** : `">\t| a | b |\n>\t|---|---|\n>\t| p q | y |\n"`, commentaire sur `b`, ou `"-\t| a | b |\n\t|---|---|\n\t| p q | y |\n"`. `projection` (`src/sheafmd/comments.py` ~475) lit la colonne de `sourcepos` de pandoc, qui compte la tabulation étendue au prochain taquet ; le commentaire tombe après le `|` final (le tableau devient un paragraphe) ou dans le rang de délimitation. Main casse plus de cellules ; la PR 296 n'en casse que l'en-tête. À faire : convertir la colonne en décalage en tenant compte des tabulations, test rouge d'abord, avec une comparaison à pandoc.
2. **(c, limite du SPEC 10.4) Des accents graves isolés dans un tableau cité ou dans une liste sont refusés** comme un code qui court d'une cellule à l'autre (`> | p ` q | r ` s |`, commentaire sur `q`), alors que pandoc n'y voit pas de code. Rien n'est perdu (`AnchorError`). À faire : que `parse` masque le code cellule par cellule sur les rangs de tableau d'une citation ou d'une liste (`in_table_row`), puis retirer la limite (1) du SPEC ; ou la garder.

**Blocked by:** none

**Claimed by:** Isolde

**Par où commencer :** `tests/test_anchoring.py`, après la section « ticket 68 » : un test rouge par point.

- [x] Point 1 corrigé, test rouge d'abord (PR 307, `off()` de `projection`)
- [x] Point 2 : gardé comme limite, déplacé au ticket 87. Raison : cinq rondes de revue de la PR 307 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-75-reviews/`) ont chacune trouvé le bord suivant d'une lecture à la main des marqueurs de conteneur (citation dans un item, item dans une citation, tabulations, `>` sans espace, titre, plusieurs tableaux) où la PR était pire que main ; la limite (1) du SPEC 10.4 reste
- [x] CI verte

**Status:** done (PR 307, point 1 seul ; point 2 gardé comme limite, déplacé au ticket 87)
