# 58: Titres à cas limites : un titre avec espace insécable après les `#` fait planter `add_comment`, et trois cas voisins

**What to build:** Constats de la revue 2 du ticket 55 (`pr-271-reviews/opus-2.md`), tous classe c :
1. `blocks.ATX_RE` accepte tout `\s` après les `#`, `_ATX_TEXT` (comments.py:526) seulement espace ou tab : `#<espace insécable>Foo` ou `#<espace pleine chasse>見出し` est un bloc « titre », `heading_anchor` rend None alors que pandoc voit un paragraphe et `anchor_point` réussit ; `add_comment` fait `offset + None` (comments.py:551, 581) : TypeError, commentaire refusé, traceback au CLI. Avant le ticket 55 le bloc allait après la sélection. Correctif : retomber sur `point`, ou lever `AnchorError`.
2. `# #` / `### ###` (titre vide) : `_ATX_TEXT` prend le premier espace dans le groupe 1, la séquence de fermeture ne correspond pas et `heading_anchor` rend la fin de ligne : un bloc posé là ferait lire « ### » comme texte. Atteint seulement par le repli de `_insert_comment`.
3. `# The <!-- marker` (ouvreur non fermé hors code) : le bloc écrit au bout du titre ferme l'ouvreur et fait disparaître « marker » du rendu.
4. Existant, pas causé par le 55 : `_written_block` qui déplace un commentaire multi-lignes d'un paragraphe vers un titre le fait déborder de la ligne.
Classe : c.

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

- [ ] Un titre `#<espace insécable>Foo` : commentaire ajouté sans erreur, bloc à un endroit qui garde les mots — preuve : test de `add_comment`, rouge avant
- [ ] `### ###` : `heading_anchor` rend None, le bloc va sur sa propre ligne
- [ ] Un titre avec `<!--` non fermé : décision écrite (refuser, ou bloc avant l'ouvreur) et test
- [ ] Cas 4 : décision écrite
