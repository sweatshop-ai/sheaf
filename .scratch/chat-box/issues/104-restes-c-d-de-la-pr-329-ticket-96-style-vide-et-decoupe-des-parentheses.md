# 104: Restes c et d de la PR 329 (ticket 96) : un style réduit à des séparateurs, la découpe dans les parenthèses, noms et tests

**What to build:** Restes de la revue Opus de la PR 329 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-96-reviews/opus-1.md`), dans `src/sheafmd/sanitize.py` et `tests/test_sanitize.py`.

1. **C1.** Un style réduit à des séparateurs ou à des commentaires n'est pas supprimé : `;;-webkit-user-modify:x` donne `style=";"`, `/* c */; -webkit-user-modify:x` donne `style="/* c */"`. Inoffensif ; le mode mount supprime l'attribut. Tester « plus aucune déclaration » au lieu de `clean.strip()`.
2. **C2.** La découpe coupe encore sur un `;` dans `()`, `[]`, `{}` (`url(data:image/png;base64,…)`), où un navigateur ne coupe pas. Ne peut que retirer trop. Décider : suivre la profondeur des parenthèses, ou le noter dans la SPEC.
3. **D1.** `_USER_MODIFY` retient aussi la barre oblique inverse ; le nom ment. Le renommer.
4. **D2.** Le cas `mount=True` de `test_a_style_the_filter_empties_is_removed` teste un comportement antérieur à la PR.

**Blocked by:** PR 329 fusionnée

**Status:** ready-for-agent
