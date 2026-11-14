# 99: Restes c/d de la PR 325 (ticket 83) : phrase de la SPEC sur le lien, test d'épinglage, docstring, passage Codex des PR 300 et 303

**What to build:** Restes de la revue Opus de la PR 325 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-83-reviews/opus-1.md`). La PR a été réduite aux points 1, 2 et 4 du ticket 83 (Rhea, 2026-11-14) : le point 3 (précédence de la note sur l'ouvreur vide, reconnaissance de la tête) en est sorti entièrement, `<!-->` avec une note donne le comportement de main. À reprendre :
- **(c)** `SPEC.md` 6.2 : « one in a link destination is copied » n'est vrai que si aucune flèche ne suit : `[l](http://x/<!-->) KEEP1` suivi de `KEEP2 <!-- c -->` est refusé avec le message « swallows » (sûr, main fait pareil). Dire les deux cas.
- **(b/c)** Fait dans la PR 325 : le commentaire du test dit qu'il épingle la phrase de la SPEC et passe aussi sur main.
- **(d)** `src/sheafmd/comments.py:697`, docstring de `cell_end` (F3.1 de la revue de la PR 303) : « unless an odd run of backslashes escapes it » est faux depuis la PR 303, tout antislash juste avant le `|` l'échappe.
- **(a) Point 3 du ticket 83, à refaire : `<!-->` et une note de relecteur sur la même ligne.** Voulu : une note non fermée est nommée avant l'ouvreur vide (main donne le message de l'ouvreur vide, le message de la note est plus utile, rien ne fuit dans les deux cas). Trois revues de la PR 325 (`pr-83-reviews/opus-1.md`, `opus-2-narrow.md`, `opus-3-narrow.md`) ont trouvé trois a dans ce seul bloc :
  1. une note FERMÉE avant `<!-->` (`# A <!-- sheaf-comment ... hi --> b <!--> c`) donnait « note jamais fermée » ; corrigé en excluant les têtes dans un `COMMENT_RE.span` de la ligne ;
  2. une tête écrite en CODE (`A <!--> b `<!-- sheaf-comment x` c`) donnait le message de la note ; corrigé en exigeant que la queue de ligne figure dans `frag` ;
  3. cet `in frag` verbatim ratait une tête brute dont la ligne a une tabulation ou du texte décomposé (NFD), que pandoc réécrit (tab → espaces, NFC) ; corrigé en normalisant la queue (`expandtabs(4)`, NFC) ;
  4. (rare, jamais corrigé) tête coupée sur deux lignes dont la première moitié est du code et dont le reste (`<!-- sheaf-comment`) se retrouve ailleurs dans `frag` : le test regarde le document entier, pas la ligne.
  **Leçon :** reconnaître une tête doit lire la sortie de pandoc à la position de la ligne (sourcepos : `<code data-pos>` ou non), jamais une correspondance verbatim d'une chaîne de la source dans `frag`. Les tests écrits (rouges d'abord) sont dans l'historique de la branche chat-box/83 (commits a2e58cb, c1b32f9, 8034921) avant leur retrait en 3af54e9.
- **(c)** Revue 4 (`pr-83-reviews/r4-narrowed.md`), rien de pire que main : SPEC 6.2 dit « refusé que `-->` suive ou non », or `# A <!--> -->` est copié (la flèche suivante ne prend aucun mot montré) ; dire « refusé quand le retrait perdrait un mot ». Et `# A <!--> b <!-- c` ne nomme que l'ouvreur vide, pas le `<!-- c` non fermé de la même ligne (même chose sur main).
- **Passage Codex dû (point 5 du ticket 83) :** `/codex-review --base` sur le diff de la PR 300 (merge 1521562, tête 190bc94) et sur celui de la PR 303 (fusionnée ff5aaf7). Codex est sans jetons jusqu'à 20 h le 2026-11-14 ; ses trouvailles deviennent des tickets ou des corrections.

**Blocked by:** PR 325 fusionnée (pour la SPEC) ; le passage Codex attend 20 h.

**Claimed by:**

**Status:** ready-for-agent
