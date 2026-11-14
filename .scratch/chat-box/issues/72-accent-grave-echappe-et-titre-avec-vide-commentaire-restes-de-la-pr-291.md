# 72: Accent grave échappé ignoré par `CODE_SPAN_RE`, et un titre avec `<!-->` plus un commentaire refusé par la copie à partager, restes de la PR 291

**What to build:** Deux restes (classe d) des revues Opus de la PR 291 (ticket 66, fusionnée en 0b469e2), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-66-reviews/opus-1.md` et `handoff-Arvid-2026-11-14.md`. Tous deux existent déjà sur main.
1. **`CODE_SPAN_RE` (`src/sheafmd/comments.py` ~59) ignore la barre oblique inverse devant un accent grave** : un accent grave échappé ouvre un code en ligne que pandoc ne voit pas. Un commentaire se perd : ``# Use \` then <!-- see `x` `` place le commentaire après `` `x` `` puis l'ouvreur cache « see `x` » du titre ; ``Type a \` to quote. The word<!-- sheaf-comment …--> and `x` here.`` : `parse` ne trouve pas le commentaire. À faire : donner à `CODE_SPAN_RE` le préfixe `(?<!\\)(?:\\\\)*` que les balises et les ouvreurs ont, avec un test rouge d'abord et une comparaison avec pandoc dans `test_parse_reads_text_that_looks_like_a_tag_or_comment_as_pandoc_does`. Voir aussi le point 3 du ticket 68, qui touche les accents graves échappés en tableau : à faire ensemble.
2. **Un titre avec `<!-->` (ou `<!--->`) plus un commentaire est refusé par la copie à partager**, sur main comme avec la PR 291 : `render.COMMENT_RE` (`render.py:41`, `<!--[\s\S]*?-->`) ne connaît pas `<!-->` et court jusqu'au `-->` du commentaire écrit ; `UnclosedComment`. Rien n'est perdu en silence, la garde refuse la page. Élargir l'expression casse deux tests de garde de `tests/test_share_copy.py` (le cas `<http://x/<!--> b`, où pandoc lit autrement, et `test_text_in_code_between_a_quoted_opener_and_a_later_arrow_is_lost_by_decision_and_logged`). À faire : décider si la retirer vaut ces deux gardes (le sens de `<!-->` dépend du contexte : texte, lien automatique, attribut), ou écrire la limite dans le SPEC 10.4.

**Recouvrement avec le ticket 68 :** les accents graves appariés à travers des cellules et des rangs sont couverts par 68 (PR 296, merge 0e723e9) ; un accent grave échappé à l'intérieur d'une seule cellule ou d'un paragraphe reste à ce ticket.

**Blocked by:** none

**Claimed by:**

**Fait :** PR 300, merge 1521562. Point 1 : corrigé, test rouge d'abord ; `CODE_SPAN_RE` est devenu `_CodeSpanFinder` (l'ouvreur par motif avec le préfixe de barres obliques inverses, le fermeur par recherche dans les suites d'accents graves du bloc), identique à l'ancienne expression sur plus de 40 000 chaînes tirées au hasard et à pandoc sur la comparaison par empan. Point 2 : décidé, pas codé. `render.COMMENT_RE` reste ce qu'il est et la limite est écrite dans le SPEC 6.2 : un `<!-->` ou `<!--->` dans un texte courant, un titre ou une liste fait refuser la copie à partager, avec ou sans commentaire après lui, parce que pandoc le lit comme un commentaire dans le texte mais comme une partie de l'adresse dans une destination de lien (`[l](http://x/<!-->)`), que la copie fait sans perte. Un test le fixe. Revues : Opus en deux passes (Codex sans jetons jusqu'à 15 h), GO deux fois, tout corrigé. Restes : ticket 76.

**Status:** done

**Par où commencer :** `tests/test_anchoring.py`, section « ticket 66 » : un test rouge pour le point 1 (`parse` doit trouver le commentaire après `\``).

- [x] Point 1 corrigé, test rouge d'abord
- [x] Point 2 décidé : la limite écrite dans le SPEC 6.2 (et non 10.4, où la copie à partager n'est pas décrite)
- [x] CI verte (3/3 sur 190bc94, total_count 3)
