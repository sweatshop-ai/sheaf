# 65: Titres : une régression sur les titres faits de dièses, et finitions, suites de la revue Opus 1 de la PR 285

**What to build:** Constats de classe c et d de la revue Opus 1 de la PR 285 (GO, aucun défaut a ni b), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-56-reviews/opus-1.md`, tête f14d253. Non corrigés dans la PR. Numéros de ligne de cette tête, à relire. Classe c et d, à décider un par un : corriger, ou écrire la limite dans le SPEC 10.4.
1. **Régression (c)** `## ## ##` et `#  #  #` s'affichent comme des titres qui ont des mots (`##`, `#`), mais `heading_anchor` (comments.py ~559, `set(m.group(2)) == {"#"}`) les tient pour vides : un commentaire est refusé, il était accepté avant la PR 285. À faire : tester la ligne entière, seuls les dièses de fermeture non reconnus sont un titre vide (`### ###`, `# #`, `## #`).
2. (c) `_mask_code` ne saute que les commentaires sheaf : un accent grave dans une balise HTML brute ou un commentaire ordinaire fermé peut s'apparier à un suivant et cacher un vrai `<!--` (``# a <span title='`'>s</span> <!-- b `x``) ; le bloc écrit à la fin le ferme, « b `x » disparaît. À faire : lire de gauche à droite comme `_comment_spans` (comments.py ~654), ou écrire la limite.
3. (c) Un commentaire sur des mots après un `<!--` non fermé (`# The <!-- marker`, « marker » choisi) est écrit avant l'ouvreur ; `rangeFor` (page.js ~476) ne cherche que le texte avant l'ancre : pas de surlignage. À faire : écrire la limite dans le SPEC 10.4, ou refuser.
4. (c, hors du diff) Un commentaire multi-lignes que le merge déplace dans une cellule de tableau casse la ligne du tableau (`ONE_LINE_KINDS` contient `table`, edit.py `_insert_comment`). À faire : `own_line` pour `b.kind in rdc.ONE_LINE_KINDS`, avec un test.
5. (d) Tests : `_insert_comment` avec un titre `### ###` met le bloc sur sa propre ligne (case du ticket 58 non prouvée) ; renforcer le test de l'ouvreur non fermé (il ne vérifie que « marker » dans la page) ; un test setext a été ajouté, pas pour `# <!-- x` en ATX avec un mot avant.
6. (d) Le SPEC 10.4 nomme des symboles du code (`rangeFor`, `_occurrence`, `blocks.ATX_RE`) : les remplacer par ce que fait le code.

**Blocked by:** none


**Claimed by:** Kofi 2026-11-14 01:26

**Status:** in-progress

**Par où commencer :** `tests/test_anchoring.py` : `## ## ##` accepte un commentaire (rouge avant) ; puis le point 4 dans `tests/test_edit_followups.py`.

- [ ] Point 1 corrigé, avec son test rouge d'abord
- [ ] Points 2 à 4 corrigés ou la limite écrite dans le SPEC 10.4, chacun avec son test
- [ ] Points 5 et 6 faits
- [ ] CI verte
