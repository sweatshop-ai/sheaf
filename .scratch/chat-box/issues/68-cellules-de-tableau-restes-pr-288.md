# 68: Cellules de tableau : `<!-->` refusé, le merge sur un dernier rang sans `|` final, et trois cas que `parse` ou le découpeur de blocs lisent autrement que pandoc, restes des revues Opus de la PR 288

**What to build:** Constats de classe c des deux revues Opus de la PR 288 (ticket 57, fusionnée en fd23dee ; GO au tour 2, aucun défaut a ni b), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-57-reviews/opus-1.md` et `opus-2.md`, et la fin de `handoff-Amelie-2026-11-14.md`. Tête relue : 6bdadd4. Classe c, à décider un par un : corriger, ou écrire la limite dans le SPEC 10.4.
1. **(c, introduit par 57, rare) Une cellule avec `<!-->` est refusée** (`| <!--> w | y |`, commentaire sur « w » : `AnchorError`, « this cell has no place for a comment »). Main écrivait le bloc. Par `_insert_comment` l'exception est avalée et le bloc tombe à la fin du tableau. C'est le même correctif que le point 3 du ticket 66 (`<!-->` et `<!--->` tenus pour non fermés par `_unclosed_opener`, que pandoc lit comme un commentaire vide fermé) : voir 66, ne pas le refaire ici ; ajouter seulement un test de cellule quand 66 est fait.
2. **(c, déjà sur main) `_insert_comment`, dernier rang sans `|` final avec un `<!--` non fermé dans sa dernière cellule** : `cell_end` lève, le `except` garde la fin du bloc, et le bloc ferme l'ouvreur et cache les mots de la cellule (`| y | <!-- x w` donne `| y | <!-- x w<!-- sheaf-comment … -->`). `add_comment` refuse proprement. À faire : pour un tableau, dans le `except`, mettre le bloc sur une ligne à lui après le tableau.
3. **(c, déjà sur main) `parse` / `_mask_code` appariait les accents graves à travers les cellules et les rangs, et un accent grave échappé aussi** : un commentaire sur des mots dans un tel intervalle n'est pas listé (`| a ` b | one two | c ` |`, commentaire sur « one » ; `| a \` b z | c |` puis `| d \` e | f |`, sur « b »). `cell_end` retombe sur la fin de la sélection dans ce cas, ce que main fait déjà. À faire : lire par cellule dans un tableau, ou écrire la limite dans le SPEC 10.4.
4. **(c, déjà sur main) Un tableau dans une liste ou une citation** est un bloc `list` ou `quote`, pas `table` : le commentaire va encore au milieu de la cellule, et `add_comment` écrit la forme sur plusieurs lignes, qui casse le rang, alors que `_insert_comment` écrit une ligne. À faire : reconnaître le tableau dans ces blocs, ou écrire la limite.
5. **(c, déjà sur main) Un rang paresseux sans `|` après un tableau** est un `para` pour `split_md_blocks` et un rang pour GFM : le commentaire va au milieu du texte du rang. À faire : décider si le découpeur suit GFM, ou écrire la limite.

**Blocked by:** none (le point 1 est débloqué par 66, fusionné en 0b469e2)

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** `tests/test_anchoring.py`, après les tests « table cells (ticket 57) » : un test rouge par point, en commençant par le 2 (`rde._insert_comment` sur un tableau dont le dernier rang finit par `<!-- x w`).

- [ ] Point 1 : un test de cellule `<!-->` vert après le ticket 66
- [ ] Point 2 corrigé, test rouge d'abord
- [ ] Points 3 à 5 corrigés ou la limite écrite dans le SPEC 10.4, avec la raison
- [ ] CI verte
