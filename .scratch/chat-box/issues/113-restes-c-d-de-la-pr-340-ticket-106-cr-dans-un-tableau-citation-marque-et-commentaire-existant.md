# 113: Restes c et d de la PR 340 (ticket 106): des CR dans un tableau, une marque ou un commentaire existant

**What to build:** Restes de la revue Opus de la PR 340, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-106-reviews/opus-1.md`. Ni a ni b ; tous déjà vrais sur main sauf mention.
- c2 : un CR dans la marque (`-\r [ ]`, `- [ ]\r b`) dans une liste qui a aussi un item vide `- [ ]` : pandoc 3.9 dessine cet item comme le texte ☐ sans case, mais le `|$` de `TASK_MARK_RE` le compte comme marque. `'- [ ]\n-\r [ ] b\n'` : la page coche « b », `_toggle_boxes` rend `'- [x]\n-\r [ ] b\n'` (mauvaise ligne). Très étroit.
- c3 : `in_table_row` / `_CONTAINER_RE` ne saute pas un CR avant `>` : dans `'\r> | a | b |\n\r> |---|---|\n…'` le commentaire s'écrit sur plusieurs lignes dans la ligne du tableau et la page montre `<!--`.
- c4 : `cell_end` ne voit pas une barre oblique inverse devant un CR : `'| x\\\r | y |'` donne `x\<!--`, le commentaire s'affiche en texte.
- c6 : un CR dans l'ouverture d'un commentaire existant le cache à `parse` ; le nouveau commentaire prend un id en double.
- c1 (relecture r2-narrow.md) : `_toggle_boxes` compare la liste des états, pas la ligne de chaque marque. Un CR après la marque ou dans les crochets (`- \r[ ] B`) fait manquer une case dessinée ; avec un `[ ]` dans un bloc de code de la même liste, les comptes concordent et la coche tombe sur la mauvaise ligne : `'- x\n  ```\n  - [ ] A\n  ```\n- \r[ ] B\n'`, cocher B écrit `- [x] A` dans le code. Vrai avant et après PR 340. Piste : comparer la ligne de chaque marque à celle de chaque case.
- d5 : `cell_end` ne saute pas un CR dans les espaces avant `|` (HTML identique, espaces près).
- d7 : le commentaire tombe après une suite de CR (`Title\r<!--…-->\n`), HTML identique.

À mesurer contre pandoc 3.9, test rouge d'abord ; chaque reste est corrigé ou écarté avec la preuve.

**Blocked by:** none

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] c2, c3, c4, c6 corrigés ou écartés avec la preuve
- [ ] d5, d7 notés ou corrigés
