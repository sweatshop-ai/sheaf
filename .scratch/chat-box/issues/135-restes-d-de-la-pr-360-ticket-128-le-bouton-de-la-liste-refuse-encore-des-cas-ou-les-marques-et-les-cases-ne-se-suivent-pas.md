# 135: Restes d de la PR 360 (ticket 128) : le bouton de la liste refuse encore des cas où les marques et les cases ne se suivent pas une à une

**What to build:** Reste d de la relecture Opus du correctif de la PR 360 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-128-reviews/opus-2.md`). Depuis le correctif (tête 4d49138), `box_place` donne la bonne case (celle que le rendu dessine). `ticked_html` exige encore que les marques d'une lecture soient les cases, une pour une. Restent refusés par `tick_edit` (main les refusait aussi, rien n'est perdu) : `- [ ] Approve\n- [ ]\n- [ ] Done`, `- [ ]\n  - [ ] Approve`, une `<input>` brute à côté de l'action, CRLF avec un élément vide. Piste : une lecture « marques qui ont une case », bâtie avec `box_number`, une fois par bloc et gardée comme lui. Fuzzer par le chemin de la liste (`the_list.box_place` et `tick_edit`) contre origin/main : 0 faux, 0 pire.

**Blocked by:** PR du ticket 128 fusionnée

**Claimed by:** Yuki 2026-11-15 12:49

**Status:** done, PR 371 merged (cadd9d6)

- [x] les quatre cas ci-dessus écrivent en place, ou chacun est écarté avec la preuve
