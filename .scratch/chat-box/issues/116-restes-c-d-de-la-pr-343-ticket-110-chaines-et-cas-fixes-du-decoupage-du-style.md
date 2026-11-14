# 116: Restes c et d de la PR 343 (ticket 110) : chaînes avec échappement hexa + saut de ligne, mutants vivants du test

**What to build:** Restes de la revue Opus de la PR 343 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-110-reviews/opus-1.md`), verdict GO. Aucun ne peut cacher `user-modify` ou une barre oblique inverse.

1. **c.** Dans une chaîne, CSS laisse un échappement hexa prendre une espace blanche (saut de ligne compris) : `"\41<LF>;…"` est une seule chaîne. `_declarations` et la référence de test terminent la chaîne au saut de ligne. Idem `\`+CRLF, et CR/FF ne terminent pas la chaîne dans la référence. Corriger les deux, ou écrire la limite dans SPEC 9.5 (« le découpage suit le tokenizer » est trop fort sur ce point).
2. **c.** Deux mutants survivent : retirer le contrôle `value[i] == "("` (un `url` nu ouvre un jeton url) ; traiter `\`+saut de ligne comme échappement dans un nom. Ajouter à `SPLIT_CASES` `a:url ;b:c)d;e:f` et `a:\<LF>url(/*);b:c`, et au fuzz les pièces `\41<LF>`, `\<LF>` et `url` nu.
3. **c.** SPEC 9.5 : « un fermant sans ouvrant est ignoré » est plus étroit que le code, qui ignore tout fermant qui ne ferme pas le bloc le plus interne.
4. **d.** `<!--url(` (CDO puis jeton url ; `_NAME_RUN` lit `--url`), NUL/CR/FF hors chaîne, `isdigit()` Unicode dans la référence, `_unescaped` rend une substitution isolée : ne déplacent qu'une coupure.

**Blocked by:** PR 343 fusionnée

**Claimed by:** Marisol

**Status:** ready-for-agent
