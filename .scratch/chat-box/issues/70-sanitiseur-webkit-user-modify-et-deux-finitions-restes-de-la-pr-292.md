# 70: Sanitiseur : `-webkit-user-modify` en mode simple, un cas de test et une ligne de commentaire, restes de la revue Opus 1 de la PR 292

**What to build:** Trois restes (un c, deux d) de la revue Opus 1 de la PR 292 (ticket 67), dans `src/sheafmd/sanitize.py` et `tests/test_sanitize.py`.

1. **c1.** Le mode simple garde tout attribut `style`, et la CSP du hub autorise le style en ligne (`hub/auth.py:75`). `<span style="-webkit-user-modify: read-write">x</span>` fait, dans un moteur qui honore encore cette propriété, une zone éditable que `e.target.closest('[contenteditable="true"]')` (page.js ~3260) ne trouve pas : le trou que le ticket 67 a fermé pour l'attribut. Le mode mount n'est pas touché (sa liste blanche de styles retire la propriété). À vérifier d'abord dans un navigateur, sur t-compute (jamais sur le portable) : si la zone s'édite, retirer la propriété en mode simple, sinon dire dans SPEC 9.5 que la règle ne couvre que l'attribut.
2. **d1.** `test_the_document_has_no_contenteditable_of_its_own` n'a aucun cas avec un nom d'attribut en majuscules ni en double (`CONTENTEDITABLE`, `contenteditable="true" contenteditable="false"`). Les deux sont déjà bien traités ; le test les fixerait.
3. **d2.** Le commentaire de `sanitize.py:65` fait 115 caractères, les lignes voisines se coupent vers 88.

**Blocked by:** none

**Établi (preuves) :** `/home/tiroir/.claude/pm/chat-box-handoffs/pr-67-reviews/opus-1.md` (c1, d1, d2), 56 entrées passées dans `sanitize()` sans qu'un `contenteditable` survive. c1 n'a pas été essayé dans un navigateur.

**Par où commencer :** pour c1, une page de test minimale avec le span ci-dessus dans Chromium, Firefox et WebKit sur t-compute ; noter lesquels laissent taper.

- [ ] c1 essayé dans les trois moteurs sur t-compute, résultat écrit dans le ticket
- [ ] Si un moteur laisse taper : la propriété est retirée en mode simple, test rouge avant le correctif ; sinon SPEC 9.5 dit que la règle ne couvre que l'attribut
- [ ] Un cas en majuscules et un cas en double dans le test de `contenteditable`
- [ ] Le commentaire de `sanitize.py:65` se coupe comme ses voisins
- [ ] PR séparée, CI verte

**Status:** ready-for-agent
