# 72: Accent grave échappé ignoré par `CODE_SPAN_RE`, et un titre avec `<!-->` plus un commentaire refusé par la copie à partager, restes de la PR 291

**What to build:** Deux restes (classe d) des revues Opus de la PR 291 (ticket 66, fusionnée en 0b469e2), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-66-reviews/opus-1.md` et `handoff-Arvid-2026-11-14.md`. Tous deux existent déjà sur main.
1. **`CODE_SPAN_RE` (`src/sheafmd/comments.py` ~59) ignore la barre oblique inverse devant un accent grave** : un accent grave échappé ouvre un code en ligne que pandoc ne voit pas. Un commentaire se perd : ``# Use \` then <!-- see `x` `` place le commentaire après `` `x` `` puis l'ouvreur cache « see `x` » du titre ; ``Type a \` to quote. The word<!-- sheaf-comment …--> and `x` here.`` : `parse` ne trouve pas le commentaire. À faire : donner à `CODE_SPAN_RE` le préfixe `(?<!\\)(?:\\\\)*` que les balises et les ouvreurs ont, avec un test rouge d'abord et une comparaison avec pandoc dans `test_parse_reads_text_that_looks_like_a_tag_or_comment_as_pandoc_does`. Voir aussi le point 3 du ticket 68, qui touche les accents graves échappés en tableau : à faire ensemble.
2. **Un titre avec `<!-->` (ou `<!--->`) plus un commentaire est refusé par la copie à partager**, sur main comme avec la PR 291 : `render.COMMENT_RE` (`render.py:41`, `<!--[\s\S]*?-->`) ne connaît pas `<!-->` et court jusqu'au `-->` du commentaire écrit ; `UnclosedComment`. Rien n'est perdu en silence, la garde refuse la page. Élargir l'expression casse deux tests de garde de `tests/test_share_copy.py` (le cas `<http://x/<!--> b`, où pandoc lit autrement, et `test_text_in_code_between_a_quoted_opener_and_a_later_arrow_is_lost_by_decision_and_logged`). À faire : décider si la retirer vaut ces deux gardes (le sens de `<!-->` dépend du contexte : texte, lien automatique, attribut), ou écrire la limite dans le SPEC 10.4.

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** `tests/test_anchoring.py`, section « ticket 66 » : un test rouge pour le point 1 (`parse` doit trouver le commentaire après `\``).

- [ ] Point 1 corrigé, test rouge d'abord
- [ ] Point 2 décidé : corrigé sans casser les deux gardes, ou la limite écrite dans le SPEC 10.4
- [ ] CI verte
