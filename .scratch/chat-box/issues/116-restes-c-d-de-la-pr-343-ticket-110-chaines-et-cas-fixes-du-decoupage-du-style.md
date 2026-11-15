# 116: Restes c et d de la PR 343 (ticket 110) : chaînes avec échappement hexa + saut de ligne, mutants vivants du test

**What to build:** Restes de la revue Opus de la PR 343 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-110-reviews/opus-1.md`), verdict GO. Aucun ne peut cacher `user-modify` ou une barre oblique inverse.

1. **c.** Dans une chaîne, CSS laisse un échappement hexa prendre une espace blanche (saut de ligne compris) : `"\41<LF>;…"` est une seule chaîne. `_declarations` et la référence de test terminent la chaîne au saut de ligne. Idem `\`+CRLF, et CR/FF ne terminent pas la chaîne dans la référence. Corriger les deux, ou écrire la limite dans SPEC 9.5 (« le découpage suit le tokenizer » est trop fort sur ce point).
2. **c.** Deux mutants survivent : retirer le contrôle `value[i] == "("` (un `url` nu ouvre un jeton url) ; traiter `\`+saut de ligne comme échappement dans un nom. Ajouter à `SPLIT_CASES` `a:url ;b:c)d;e:f` et `a:\<LF>url(/*);b:c`, et au fuzz les pièces `\41<LF>`, `\<LF>` et `url` nu.
3. **c.** SPEC 9.5 : « un fermant sans ouvrant est ignoré » est plus étroit que le code, qui ignore tout fermant qui ne ferme pas le bloc le plus interne.
4. **d.** `<!--url(` (CDO puis jeton url ; `_NAME_RUN` lit `--url`), NUL/CR/FF hors chaîne, `isdigit()` Unicode dans la référence, `_unescaped` rend une substitution isolée : ne déplacent qu'une coupure.

**Blocked by:** PR 343 fusionnée

- [x] Point 1 : chaînes avec échappement hexa + espace blanche (saut de ligne, CRLF), `\`+CRLF et CR/FF fin de chaîne : corrigés dans le code et la référence, tests rouges d'abord (PR 348)
- [x] Point 2 : les deux mutants meurent (`SPLIT_CASES` et pièces du fuzz), vérifié à la main et par la revue Opus (4 mutants + 5 autres)
- [x] Point 3 : SPEC 9.5, phrase du fermant et « le découpage suit le tokenizer » réécrites
- [x] Point 4 : `<!--` sauté comme un jeton, `isdigit` ASCII dans la référence ; NUL/CR/FF hors chaîne et `_unescaped` : ticket 124 (PR du ticket 124)
- [x] Revue Opus GO (pr-116-reviews/opus-1.md), CI verte (PR 348)

**Claimed by:** Marisol

**Status:** done (PR 348, merge 077a2c9)
