# 66: Titres : un balayage quadratique et un accent grave dans un commentaire fermé, restes de la revue Opus 1 de la PR 286

**What to build:** Constats de classe c et d de la revue Opus 1 de la PR 286 (GO, aucun défaut a ni b) et de la revue des normes, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-65-reviews/opus-1.md`, tête beb6110. Le constat F1 (`_HTML_TAG_RE`) est corrigé dans la PR 286. Numéros de ligne de cette tête, à relire. Classe c et d, à décider un par un : corriger, ou écrire la limite dans le SPEC 10.4.
1. **(c, régression de la PR 286) `_unclosed_opener` est quadratique** (`src/sheafmd/comments.py`, ~543-561) : chaque passe refait trois recherches depuis la position courante. Un titre setext de 9 Ko avec 1000 balises puis `<!--` : 1,6 s (main : 0,002 s) ; 36 Ko et 4000 balises : 21,8 s ; un titre ATX de 16 Ko : 8,0 s. `_insert_comment` appelle `heading_anchor` deux fois (edit.py ~1658) et le hub est bloqué pendant ce temps. À faire : réutiliser chaque résultat de recherche tant qu'il est devant la position, comme `_mask_code`, avec un test de durée sur un long titre.
2. **(c, déjà sur main) `_mask_code` : un commentaire ordinaire fermé ne possède pas son accent grave** : dans ``See <!-- todo `x --> the word and use `code` here.``, le commentaire écrit sur « word » n'est pas trouvé par `parse`, sur main comme sur la tête. Le point 2 du ticket 65 n'est corrigé que dans `_unclosed_opener` et pour les balises. À faire : lire de gauche à droite comme `_comment_spans` (un commentaire fermé qui commence avant un accent grave le possède), ou écrire la limite dans le SPEC 10.4.
3. **(d) `_unclosed_opener` tient `<!-->` pour non fermé**, alors que le lecteur de la liste (`hub/the_list.py` ~325) le lit comme un commentaire entier, comme CommonMark. Rien n'est perdu. À faire : aligner les deux, avec un test.
4. **(d) Le même balayage deux fois** : `_mask_code` et `_unclosed_opener` implémentent chacun la précédence CommonMark (accent grave, balise, commentaire) ; `render.py` ~603 et `hub/the_list.py` ~359 appellent `_mask_code`. À faire : un seul balayeur partagé.
5. **(d) Tests manquants** : (a) `parse` est d'accord avec pandoc sur un texte qui ressemble seulement à une balise (la PR 286 en a ajouté six cas, pas de comparaison systématique), (b) une borne de durée sur un long titre (voir 1).
6. **(d) `heading_anchor`** (comments.py ~582) teste « que des dièses » avec `set(lines[0][len(m.group(1)):].strip()) == {"#"}` : `m.group(2)` n'est plus ce que la condition lit, la correspondance et le test ont divergé. À faire : une seule définition de « titre vide ».

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** `tests/test_anchoring.py` : un titre de 9 Ko, 1000 balises puis `<!--`, doit se faire en moins d'une seconde (rouge avant) ; puis le point 2.

- [ ] Point 1 : `_unclosed_opener` linéaire, avec un test de durée rouge d'abord
- [ ] Point 2 corrigé ou la limite écrite dans le SPEC 10.4, avec son test
- [ ] Points 3 à 6 faits ou écartés avec la raison
- [ ] CI verte
