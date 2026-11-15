# 120: Restes c et d de la PR 347 (ticket 113): c7, _unstrip et nits

**What to build:** Restes de la revue Opus de la PR 347, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-113-reviews/opus-1.md`.
- c7 (écarté dans 113, preuve : rien de faux n'est écrit, la coche passe par pandoc) : une vraie case dans une liste qui a aussi un `- [ ]` dans un bloc de code ne se coche pas depuis la ligne de la liste. Il faudrait la position des cases, que pandoc ne donne pas.
- c1 : `_unstrip` lève un IndexError nu quand `at > len(keep)` ; aucun appelant n'y arrive.
- d1/d2 : le test « empty task item next to a box » passe déjà sur main ; les deux tests de coche construisent le fragment avec `ticked_html` (None dans ces cas) : construire le fragment en retournant la case dans le rendu.
- d3 : une coche fait 3 rendus au lieu de 2 (1,28 s → 2,86 s pour 200 items).
- d4 : `_Mark.end()` vaut le groupe 2 par défaut, `re.Match.end()` le groupe 0.
- d5 : `_Out` locale → `SimpleNamespace`.

**Blocked by:** none

**Claimed by:** Dalia

**Status:** done (PR 353, merged 4002440)

- [x] c1, d1, d2, d4, d5 corrigés ; c7 et d3 corrigés ou écartés avec la preuve
