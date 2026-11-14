# 94: Bloc à copier : un CR seul avant le `#` fait perdre le bouton, et restes de la relecture étroite de la PR 315

**What to build:** Restes de la relecture étroite (Opus 2) de la PR 315 sur 8c1b152, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-74-reviews/opus-2-narrow.md`. Verdict de la relecture : GO, aucun reste n'est une régression.

**Blocked by:** none

**Claimed by:** (libre)

**Status:** ready-for-agent

1. **b1 :** un CR seul dans l'indentation, avant le `#` ou en début de ligne n'est pas lu comme pandoc le lit (pandoc supprime le CR seul) : `_OPENS_BLOCK` dit False là où pandoc garde le paragraphe, donc le bouton Copier est perdu. N'est atteint que par les chemins qui lisent le texte brut ; le rendu lit avec les fins de ligne universelles. Existait avant la PR 315. Sens nuisible : à corriger, test d'abord, mesuré contre pandoc 3.9.
2. **c1 :** `#\rh` : pandoc supprime le CR, `#h` est du texte ; `[ \t\r]` dit True là où pandoc fait un titre. Même HTML sur la page et la copie partagée. Inoffensif ; à écarter ou à régler avec le point 1 (retirer les CR seuls de la ligne avant de la tester).
3. **c2 :** `blocks.ATX_RE` utilise `\s` : coupure existante de `split_md_blocks`, inoffensive (famille du ticket 74, F4).
4. **d1 :** le commentaire du test `#\r#` dans `tests/test_copy_blocks.py` dit « a lone CR is a line end for pandoc » : faux, pandoc le supprime. Les valeurs attendues sont justes ; corriger le commentaire.

- [ ] Un test rouge par point 1, vert après correctif, mesuré contre pandoc 3.9
- [ ] Les points 2 à 4 sont réglés ou écartés avec la preuve
- [ ] PR séparée, CI verte
