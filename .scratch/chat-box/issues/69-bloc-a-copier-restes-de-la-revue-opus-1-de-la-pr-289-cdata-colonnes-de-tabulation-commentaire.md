# 69: Bloc à copier : `<![CDATA[` insensible à la casse, colonnes de tabulation et commentaire de `is_copy_block`, restes de la revue Opus 1 de la PR 289

**What to build:** Trois restes de classe c de la revue Opus 1 de la PR 289 (ticket 13), dans `src/sheafmd/copyblock.py`. Aucun n'a d'effet visible : la page et la copie partagée sont les mêmes qu'avant, et un commentaire sur le marqueur tombe au bon endroit (vérifié par le relecteur).

1. `_OPENS_BLOCK` est compilé avec `re.I` : `<![CDATA[` devient insensible à la casse, et `<![cdata[` compte comme ouvreur alors que pandoc en fait un titre, donc `is_copy_block` rend True là où il devrait rendre False. Correctif : `(?-i:<!\[CDATA\[)`.
2. `^\s{0,3}` compte des caractères, pas des colonnes : `>\t  <div>` et `>\t\t<div>` sont lus comme ouvreurs alors que pandoc y voit du code indenté. Déjà vrai sur main pour les clôtures et les titres ATX ; la PR 289 le reporte aux ouvreurs HTML.
3. Le commentaire du `break` dans `is_copy_block` ne cite que « a fence, a list, a heading or a quote » : y ajouter les blocs HTML.

**Blocked by:** none

**Établi (preuves) :** `/home/tiroir/.claude/pm/chat-box-handoffs/pr-13-reviews/opus-1.md` (F1, F2, F3), 1 068 entrées comparées à `pandoc -f gfm`. Le sens nuisible (False là où pandoc garde le paragraphe du marqueur, donc un bouton perdu) n'a été trouvé sur aucune entrée.

**Par où commencer :** un test rouge par point (`<![cdata[` avant `---`, `>\t  <div>` avant `---`), puis le correctif ; pour 2, vérifier d'abord ce que fait pandoc sur chaque mélange de tabulations et d'espaces avant de choisir la règle.

- [ ] `<![cdata[` avant un soulignement refuse le bloc, `<![CDATA[` l'accepte
- [ ] `>\t  <div>` avant un soulignement refuse le bloc, comme pandoc ; les cas déjà couverts de `tests/test_copy_blocks.py` passent toujours
- [ ] Le commentaire du `break` nomme les blocs HTML
- [ ] PR séparée, CI verte

**Status:** ready-for-agent
