# 133: Restes c et d de la PR du ticket 126: un commentaire dans le texte alternatif d'une image d'un tableau du document

**What to build:** Reste de la revue du ticket 126 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-126-reviews/opus-1.md`). Mesuré contre pandoc 3.9 :
- `| ![xx<!-- sheaf-comment id=c1 … -->](u) | yy |` (tableau hors citation ou liste) : pandoc abandonne le commentaire (il n'est pas dans le HTML) mais `parse` le trouve. Dans une citation ou une liste, `parse` et pandoc sont d'accord (rien). L'écart est donc sur un tableau du document, hérité de main ; le reste R2-2 du ticket 126 était écrit à l'envers.
- Piste : lire par pandoc aussi les blocs `table` qui contiennent un commentaire et une image (même mécanisme que `_read_tables`), ou écarter avec la preuve si c'est sans effet pour la page.
- Écarté au ticket 126 avec preuve (non reproduit, environ 100 formes, dont un document CRLF, une réponse déjà présente, `edit_body`) : une réponse dont le corps contient `\r\n` donne 0 réponse ; test d'épinglage `test_a_reply_with_crlf_in_its_body_is_read_back`.

À mesurer contre pandoc 3.9, test rouge d'abord ; chaque reste est corrigé ou écarté avec la preuve.

**Blocked by:** PR du ticket 126 fusionnée

**Claimed by:** Dries 2026-11-15 00:12

**Status:** in-progress
