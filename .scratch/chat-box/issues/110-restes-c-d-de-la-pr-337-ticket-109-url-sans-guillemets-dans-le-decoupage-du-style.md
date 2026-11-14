# 110: Restes c et d de la PR 337 (ticket 109) : `url(` sans guillemets dans le découpage du style

**What to build:** Restes de la revue Opus de la PR 337 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-109-reviews/opus-1.md`), dans `_declarations` de `src/sheafmd/sanitize.py`. Aucun ne peut cacher `user-modify` : le nom est cherché dans chaque morceau entier.

1. **C1.** `@url(` et `#url(` sont lus comme des jetons url ; CSS lit un at-keyword ou un hash. Sans effet de sécurité.
2. **C2.** Un échappement juste avant `url(` (`\75 url(`, `a\:url(`) n'est pas vu comme faisant partie du nom ; le morceau contient une barre oblique inverse et tombe de toute façon.
3. **C3.** Les crochets sont comptés, non appariés (déjà documenté) ; le jeton url atteint maintenant plus de ces cas.
4. **C4.** Le test à fuzz (`test_no_split_of_a_style_lets_user_modify_or_a_backslash_through`) tient pour tout découpage aux `;` : il ne peut pas voir une régression du découpage. Ajouter une comparaison à un découpeur de référence du tokenizer CSS Syntax 3, ou des cas fixes de plus.

**Blocked by:** PR 337 fusionnée

**Status:** ready-for-agent
