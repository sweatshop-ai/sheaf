# 132: Restes c et d du ticket 128 : case d'une puce derrière un autre marqueur, et titre du corpus

**What to build:** Restes de la revue Opus du ticket 128 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-128-reviews/opus-1.md`), verdict GO, aucune écriture fausse.
1. **c1 (et b1 du rapport).** Une case dessinée par une puce derrière un autre marqueur de la même ligne (`- - [ ] x`, `1. - [ ] x`, `1. > - [ ] x`) n'a pas de marque, avant comme après le ticket 128 : tout bloc qui en contient une envoie ses coches par pandoc, qui réécrit la liste. C'est la cause qui reste des réécritures complètes, et c'est ce qui fait que 9 cas sur 990 (un bloc avec une telle case et un `1. [ ]`) repassent par pandoc après le ticket 128 alors qu'une coïncidence de comptes les laissait écrire en place avant (361 cas vont dans l'autre sens). Piste : accepter une chaîne de marqueurs `[-*+]` ou `\d+[.)]` avant la puce finale, la fin devant être une puce. Mesurer contre pandoc 3.9 et fuzzer comme la revue (la case de `- - [ ] x` et celle de `1. - [ ] x` sont dessinées ; `- 1. [ ] x` ne l'est pas). Rejoint le c7 du ticket 120.
2. **d1.** `tests/corpus/task-lists.md`, lignes 20 à 23, porte le titre « An ordered task list: » alors que pandoc ne dessine pas de case dans une liste ordonnée. Seuls les tests de pavage lisent ce fichier, rien ne casse : renommer le titre ou retirer l'affirmation.

**Blocked by:** PR du ticket 128 fusionnée

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] point 1 fait ou écarté avec la preuve ; point 2 fait
