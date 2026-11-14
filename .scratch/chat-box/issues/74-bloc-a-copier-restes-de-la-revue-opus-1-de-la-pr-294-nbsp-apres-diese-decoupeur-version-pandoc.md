# 74: Bloc à copier : restes de la revue Opus 1 de la PR 294 (ticket 69), classes c et d

**What to build:** Trois restes de la revue Opus 1 de la PR 294 (GO), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-69-reviews/opus-1.md`. Aucun n'a d'effet visible dans le sens nuisible (bouton Copier perdu).

1. F3 (c) : `#\xa0h` compte comme ouvreur de titre dans `_OPENS_BLOCK`, à cause du `\s` après les `#` ; pandoc n'y voit pas un titre. Correctif : `(?:[ \t]|$)` à la place de `\s`. Sens inoffensif (True là où pandoc fait un titre).
2. F4 (c) : 830 écarts inoffensifs viennent de `src/sheafmd/blocks.py`, `split_md_blocks` termine la citation trop tôt sur une ligne paresseuse qui ressemble à un nouveau bloc. À mesurer contre pandoc avant de décider s'il faut y toucher.
3. F6 (d) : les docs et tickets citent pandoc 3.7.0.2, mais le rendu (pypandoc-binary 1.17) tourne en pandoc 3.9. Corriger les mentions.

**Blocked by:** none

**Par où commencer :** un test rouge par point (1 : `> [!COPY]\n> a\n> #\xa0h\n> ---` refuse le bloc, comme pandoc ; vérifier d'abord avec pandoc), puis la mesure du 2.

- [x] `#\xa0h` avant un soulignement refuse le bloc, comme pandoc
- [x] Les 830 écarts de `split_md_blocks` sont classés, corrigés ou écartés avec la preuve
- [x] Les mentions de pandoc 3.7.0.2 sont corrigées en 3.9 là où le rendu est visé
- [x] PR séparée, CI verte (PR 315, 3/3 vertes sur 830be7c)

**Claimed by:** Diego

**Status:** done (PR 315, merged as 81c39b8)

**Résultat (Diego, PR 315):**
- F3 corrigé : `#{1,6}(?:[ \t\r]|$)`. Le `\r` seul compte comme fin de ligne pour pandoc (revue : `#\r#` est un titre).
- F4 écarté avec preuve, `blocks.py` inchangé : grille de 15 470 entrées (7 débuts x 5 marques x 18 mélanges x 13 ouvreurs x `---`/`===`), 2 618 coupées tôt par `split_md_blocks`. Rendu `hide` + pandoc 3.9 + `mark` comparé à pandoc seul : 1 360 (pandoc garde le paragraphe) donnent le HTML de pandoc marqueur retiré ; 1 258 (pandoc fait un titre) donnent le HTML de pandoc, à l'id près, que le rendu remplace. Nuisibles : 0. Le chiffre 830 de la revue vient d'une autre grille.
- F6 : SPEC.md ligne 177, 3.7.0.2 devient 3.9 (`pypandoc-binary==1.17`, `get_pandoc_version()` = 3.9).
- Revue Opus 1 : NO-GO sur 55b100e (classe a, `\r`), corrigé en 8c1b152.
