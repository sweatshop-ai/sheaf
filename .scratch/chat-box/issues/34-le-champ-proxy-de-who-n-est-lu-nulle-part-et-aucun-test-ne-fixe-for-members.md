# 34: Le champ `proxy` de `Who` n'est lu nulle part, et aucun test ne fixe `_for_members` pour la route de dictée

**What to build:** Dans `src/sheafmd/handler.py` (lignes 147 et 164), le champ `proxy` de `Who` n'est lu par aucun code ; il ne sert qu'à rendre `DICTATION` différent de `COOKIE` par la valeur. Aucun test ne fixe `_for_members(("transcribe-ask", DICTATION, None)) is False` : un futur test `"cookie" in who` dans `_for_members` admettrait la route. Classe : d (trouvé au tour 4 de la PR #248, ticket 06a, vérifié par lecture).

**Blocked by:**
- External: PR 248 (ticket 06a) merged into main

**Établi (preuves) :** `codex-round4.md` du tour 4 (Opus, delta a383307..ae1dae2), constat [d], marqué VERIFIED. Le 404 de `GET /_/transcribe` sur le socket proxy est déjà couvert par `test_route_access.py`, mais pas la fonction `_for_members` seule.

**Par où commencer :** soit lire `who.proxy` dans `_for_members`, soit ajouter la ligne de test qui fixe le résultat. Choisir l'un des deux, ne pas laisser un champ mort.

- [ ] `_for_members(("transcribe-ask", DICTATION, None))` vaut `False`, fixé par un test qui échoue si la route est admise
- [ ] Le champ `proxy` est lu quelque part, ou il est retiré
- [ ] `test_route_access.py` reste strict
