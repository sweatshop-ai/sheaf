# 132: Restes c et d du ticket 128 : case d'une puce derrière un autre marqueur, et titre du corpus

**What to build:** Restes de la revue Opus du ticket 128 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-128-reviews/opus-1.md`), verdict GO, aucune écriture fausse.
1. **c1 (reste).** Le ticket 128 a donné une marque à une puce derrière un autre marqueur (`- - [ ] o`, `1. - [ ] g`, `1. > - [ ] x`) et garde les marques d'avant en seconde lecture quand les comptes diffèrent (un `- [ ]` vide à côté d'une telle case). Reste : un `- [ ]` vide a une marque et pas de case, et le seul garde est le rendu du résultat. Une lecture qui connaîtrait l'élément vide (pandoc ne dessine pas de case, sauf avec une suite en retrait) supprimerait la seconde lecture. Mesurer contre pandoc 3.9 et fuzzer contre b90b6a0 comme la revue du ticket 128. Rejoint le c7 du ticket 120.
2. **d1.** `tests/corpus/task-lists.md`, lignes 20 à 23, porte le titre « An ordered task list: » alors que pandoc ne dessine pas de case dans une liste ordonnée. Seuls les tests de pavage lisent ce fichier, rien ne casse : renommer le titre ou retirer l'affirmation.

**Blocked by:** PR du ticket 128 fusionnée

**Claimed by:** Yuki 2026-11-15 12:49

**Status:** in-progress

- [ ] point 1 fait ou écarté avec la preuve ; point 2 fait
