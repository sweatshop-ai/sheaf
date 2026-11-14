# 76: Restes de la PR 300 : `_comment_spans` quadratique, message du `<!-->`, `\\|` dans un tableau et un passage Codex dû

**What to build:** Quatre restes (classe c et d) des revues Opus 1 et 2 de la PR 300 (ticket 72, GO), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-72-reviews/opus-1.md`, `opus-2.md` et `handoff-Oskar-2026-11-14.md`. Les trois premiers existent déjà sur main.
1. **(d, déjà sur main) `_comment_spans` est quadratique** (`src/sheafmd/comments.py` ~814-840). `"\`` <!--x--> " * n` : 13 Ko 0,73 s, 52 Ko 12,3 s ; du texte ordinaire `"a <!--x--> " * n` à 22 Ko : 2,0 s (0,58 s sur main avant la PR, `_opener` y était déjà quadratique). Seul appelant : `_refuse_changing_neighbours`, donc la suppression d'un commentaire dans un tel paragraphe. Entrée adverse, pas celle d'un rédacteur. À faire : garder la dernière correspondance dans `_comment_spans`, comme `_scan`, avec un test de temps linéaire.
2. **(d, déjà sur main) Le message du refus pour `<!-->` et `<!--->` est faux** (`src/sheafmd/render.py:87-89`) : « opens an HTML comment with <!-- that is never closed. In the share copy a browser would hide everything after it ». Un navigateur ferme `<!-->` tout de suite ; c'est la copie à partager qui ne sait pas le lire. À faire : un message à lui, ou le dire dans celui-ci ; le SPEC 6.2 écrit déjà que le message le dit « jamais fermé ».
3. **(d, déjà sur main) `_CELL_PIPE_RE` compte les barres obliques inverses par paires**, donc `\\|` coupe une cellule alors que pandoc gfm ne la coupe pas (`| a \\| b | c |` est une cellule `a | b`). À faire : lire comme pandoc, avec un test contre pandoc.
4. **(c) Les cas ajoutés à `test_parse_reads_text_that_looks_like_a_tag_or_comment_as_pandoc_does` ne vérifient que la présence de code dans un paragraphe**, pas quels caractères sont du code ; la comparaison par empan (revue 1 : 2 × 3 019 chaînes, 4 000 mélangées, 4 000 rangs) l'a couvert mais n'est pas dans le dépôt. À faire : ajouter un test à comparaison par empan avec un jeu fixe de chaînes.

**Passage Codex dû :** Codex n'a pas pu tourner sur la PR 300 (plus de jetons jusqu'à 15 h le 2026-11-14) ; les deux revues sont d'Opus. Faire tourner `/codex-review --base` sur le diff de la PR 300 (merge 1521562, tête 190bc94) quand il est de retour ; ses points deviennent des tickets.

**Blocked by:** none

**Claimed by:**

**Par où commencer :** `tests/test_anchoring.py`, section « ticket 72 » : un test rouge par point, en commençant par le 1.

- [ ] Point 1 corrigé, test rouge d'abord
- [ ] Point 2 corrigé
- [ ] Point 3 corrigé ou la limite gardée avec la raison
- [ ] Point 4 : test à comparaison par empan
- [ ] Passage Codex sur le diff de la PR 300 fait, ses points traités ou écartés
- [ ] CI verte

**Status:** ready-for-agent
