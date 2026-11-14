# 67: Une touche refusée dans un bloc `contenteditable` imbriqué n'a pas de marque, et les restes de la revue Opus 3 de la PR 287

**What to build:** La garde `beforeinput` de `page.js` (~3255) marque `e.target.closest('[contenteditable="true"]')`. Le sanitiseur du hub garde un `contenteditable` brut du document (`plaintext-only` et la valeur vide passent). `setEditing` (page.js ~897) ne réécrit l'attribut que sur les nœuds de premier niveau d'un bloc : un `<span contenteditable="plaintext-only">` imbriqué garde sa valeur, `closest('[contenteditable="true"]')` rend null, et une touche refusée pendant une sauvegarde y est dite par le toast sans marque (le symptôme du ticket 46). Classe : c (perte de signe, pas de perte de texte : la touche est refusée avec le toast). Le `contenteditable` propre d'un document passe le sanitiseur : c'est la même décision, pas un second défaut. Décider : le retirer au sanitiseur (comme `input`), ou marquer `e.target.closest('[contenteditable]')` quelle que soit la valeur.

**Blocked by:** none

**Établi (preuves) :** revue Opus 1 de la PR 287 (finding b) et revue Opus 3 (hors du diff : le sanitiseur garde `contenteditable`), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-46-reviews/opus-round1.md`, `opus-round3.md`, `followup-b.md`. Lecture du code et du sanitiseur ; non reproduit par un test de page, rien ouvert dans un navigateur.

**Par où commencer :** écrire la décision dans le ticket avant le code, puis un test de page avec un `<span contenteditable="plaintext-only">` dans un paragraphe et une frappe pendant une sauvegarde retenue.

- [ ] Un test de page tape dans un bloc éditable imbriqué pendant une sauvegarde sans réponse et échoue tant que le champ ne porte pas de marque
- [ ] La marque part avec la sauvegarde et ne devient pas une modification
- [ ] La décision (retirer `contenteditable` au sanitiseur, ou marquer tout `[contenteditable]`) est écrite dans le ticket avant le code
- [ ] Un cas `mount=True` dans le test paramétré `test_a_type_that_is_a_checkbox_only_after_trimming_is_no_checkbox` (tests/test_sanitize.py:126, qui ne teste que le mode simple)
- [ ] Le nom de ce test dit « trimming » alors que le cas du signe Kelvin est un pli de casse : le renommer
- [ ] `sanitize.py:12` et `SPEC.md:884` disent encore « removed unless `type="checkbox"` » : dire que le type doit être exactement `checkbox`, à la casse ASCII près

**Status:** ready-for-agent
