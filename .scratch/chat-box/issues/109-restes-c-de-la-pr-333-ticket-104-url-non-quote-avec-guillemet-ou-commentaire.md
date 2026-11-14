# 109: Reste c de la PR 333 (ticket 104) : un `url(` sans guillemets qui contient un guillemet ou `/*` emporte tout le style

**What to build:** Reste de la revue Opus de la PR 333 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-104-reviews/opus-fallback-1.md`), dans `_declarations` de `src/sheafmd/sanitize.py`. Antérieur à la PR 333, hors de son diff.

1. **C1.** Dans `background:url(/*a.png);user-modify:x;color:red` et `background:url(it's.png);user-modify:x;color:red`, `_declarations` lit `/*` ou `'` comme un commentaire ou une chaîne à l'intérieur de `url(` et court jusqu'à la fin de la valeur : tout le style est retiré, là où un navigateur garde `color:red`. Ne peut que retirer trop. Décider : lire `url(` sans guillemets comme un jeton (jusqu'au `)`), ou le noter dans la SPEC 9.5. Tests des voisins de contournement (commentaires, échappements, casse, plusieurs déclarations, blancs) si le passage change.

**Blocked by:** PR 333 fusionnée

**Status:** ready-for-agent
