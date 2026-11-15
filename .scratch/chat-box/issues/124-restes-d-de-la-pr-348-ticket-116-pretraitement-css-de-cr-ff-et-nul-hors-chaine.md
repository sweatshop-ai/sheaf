# 124: Restes d de la PR 348 (ticket 116) : prétraitement CSS de CR, FF et NUL hors d'une chaîne

**What to build:** Reste de la revue Opus de la PR 348 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-116-reviews/opus-1.md`), verdict GO. Aucun ne peut cacher `user-modify` ou une barre oblique inverse : la pièce touchée garde toujours la barre ou ne fait que déplacer une coupure. SPEC 9.5 écrit déjà la limite.

1. **d.** Hors d'une chaîne, `_declarations` et la référence de test ne font pas le prétraitement CSS 3.3 : `b\<CR>url(` et `b\<FF>url(` sont lus comme un échappement qui prolonge le nom, là où CSS (CR/FF deviennent LF) lit un delim `\` puis un jeton url ; `b<NUL>url(` est lu comme un jeton url, là où le navigateur (NUL devient U+FFFD, un caractère de nom) lit une fonction. Mesuré par Opus contre tinycss2 : 2 désaccords sur 200 000 styles bruts, tous deux `\<FF>url(`. Corriger les deux (code et référence) en normalisant d'abord l'entrée, ou laisser la limite écrite.
2. **d.** `_unescaped` rend une substitution isolée pour `\d800` (CSS : U+FFFD). Sans effet : on ne la compare qu'à `url`.

- [x] Point 1 : `\`+CR/FF n'est plus un échappement hors d'une chaîne, NUL est un caractère de nom ; code et référence ; 5 `SPLIT_CASES` rouges d'abord, pièces du fuzz, SPEC 9.5 (PR 361). 0 désaccord avec tinycss2 sur 4 × 300 000 styles (73d3568 : 14)
- [x] Point 2 : `_unescaped` rend U+FFFD pour une substitution isolée et pour `\`+NUL (ticket 131, même PR), test rouge d'abord
- [x] Revue Opus GO (pr-124-reviews/opus-1.md, reread-2-opus.md), CI verte (PR 361)

**Blocked by:** PR 348 fusionnée

**Claimed by:** Marisol 2026-11-14 23:49

**Status:** done (PR 361, merge 0dcfd38)
