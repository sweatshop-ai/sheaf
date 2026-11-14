# 74: Bloc à copier : restes de la revue Opus 1 de la PR 294 (ticket 69), classes c et d

**What to build:** Trois restes de la revue Opus 1 de la PR 294 (GO), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-69-reviews/opus-1.md`. Aucun n'a d'effet visible dans le sens nuisible (bouton Copier perdu).

1. F3 (c) : `#\xa0h` compte comme ouvreur de titre dans `_OPENS_BLOCK`, à cause du `\s` après les `#` ; pandoc n'y voit pas un titre. Correctif : `(?:[ \t]|$)` à la place de `\s`. Sens inoffensif (True là où pandoc fait un titre).
2. F4 (c) : 830 écarts inoffensifs viennent de `src/sheafmd/blocks.py`, `split_md_blocks` termine la citation trop tôt sur une ligne paresseuse qui ressemble à un nouveau bloc. À mesurer contre pandoc avant de décider s'il faut y toucher.
3. F6 (d) : les docs et tickets citent pandoc 3.7.0.2, mais le rendu (pypandoc-binary 1.17) tourne en pandoc 3.9. Corriger les mentions.

**Blocked by:** none

**Par où commencer :** un test rouge par point (1 : `> [!COPY]\n> a\n> #\xa0h\n> ---` refuse le bloc, comme pandoc ; vérifier d'abord avec pandoc), puis la mesure du 2.

- [ ] `#\xa0h` avant un soulignement refuse le bloc, comme pandoc
- [ ] Les 830 écarts de `split_md_blocks` sont classés, corrigés ou écartés avec la preuve
- [ ] Les mentions de pandoc 3.7.0.2 sont corrigées en 3.9 là où le rendu est visé
- [ ] PR séparée, CI verte

**Status:** ready-for-agent
