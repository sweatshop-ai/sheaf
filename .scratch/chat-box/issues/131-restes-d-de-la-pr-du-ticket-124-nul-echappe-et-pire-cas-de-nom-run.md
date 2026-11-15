# 131: Restes d de la revue Opus du ticket 124 (branche chat-box/124) : `\<NUL>` et pire cas de `_NAME_RUN`

**What to build:** Restes de `/home/tiroir/.claude/pm/chat-box-handoffs/pr-124-reviews/opus-1.md`, verdict GO. Aucun ne change une coupure ni ne cache `user-modify` ou une barre oblique inverse. À noter, ou à corriger si un autre ticket touche ces lignes.

1. **d. Fait** (branche chat-box/124, 254e737, test rouge d'abord) : `_unescaped("\\<NUL>")` rend `\x00` au lieu de U+FFFD. Sans effet : on ne la compare qu'à `url`.
2. **d.** Pire cas de temps, **limite connue, non corrigée** (linéaire, la corriger demanderait de réécrire la boucle principale ; mesure sur machine chargée, load 16, 2026-11-15 : `a\<CR>` ×200 000 = 1,17 s, `a\<LF>` ×200 000 = 0,95 s) : `a\<CR>` répété 200 000 fois prend 1,2 s (0,27 s avant le ticket 124 ; `a\<LF>` ×200 000 prenait déjà 1,13 s). Linéaire, pas de ReDoS ; `sanitize()` sur 90 000 caractères de ce genre : 0,14 s.

**Claimed by:** Marisol 2026-11-15

**Blocked by:** PR du ticket 124 fusionnée

**Status:** done (PR 361, merge 0dcfd38; point 1 sur chat-box/124 254e737; point 2 : limite connue écrite ci-dessus)
