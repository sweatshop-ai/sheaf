# 99: Restes c/d de la PR 325 (ticket 83) : phrase de la SPEC sur le lien, test d'épinglage, docstring, passage Codex des PR 300 et 303

**What to build:** Restes de la revue Opus de la PR 325 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-83-reviews/opus-1.md`). Le a (une note fermée avant `<!-->` donnait le message de la note) est corrigé dans la PR. À reprendre :
- **(c)** `SPEC.md` 6.2 : « one in a link destination is copied » n'est vrai que si aucune flèche ne suit : `[l](http://x/<!-->) KEEP1` suivi de `KEEP2 <!-- c -->` est refusé avec le message « swallows » (sûr, main fait pareil). Dire les deux cas.
- **(b/c)** `test_an_empty_opener_that_a_later_arrow_would_close_gets_the_swallows_message` passe aussi sur le `render.py` de main : il épingle la phrase de la SPEC, il ne teste pas un changement de la PR. Le dire dans son commentaire.
- **(d)** `src/sheafmd/comments.py:697`, docstring de `cell_end` (F3.1 de la revue de la PR 303) : « unless an odd run of backslashes escapes it » est faux depuis la PR 303, tout antislash juste avant le `|` l'échappe.
- **Passage Codex dû (point 5 du ticket 83) :** `/codex-review --base` sur le diff de la PR 300 (merge 1521562, tête 190bc94) et sur celui de la PR 303 (fusionnée ff5aaf7). Codex est sans jetons jusqu'à 20 h le 2026-11-14 ; ses trouvailles deviennent des tickets ou des corrections.

**Blocked by:** PR 325 fusionnée (pour la SPEC) ; le passage Codex attend 20 h.

**Claimed by:**

**Status:** ready-for-agent
