# 48: Un deuxième Annuler pendant que la requête du premier est en route remplace les places gardées du premier par `{}` : l'événement tardif du premier ne dit plus « had already seen it »

**What to build:** Dans `cancel(id)` de `src/sheafmd/page/page.js`, `off()` écrit `cancelled[id] = waits[id] || {}` puis `delete waits[id]`. Deux Annuler sur le même fil pendant que la requête du premier est encore en route : le deuxième `off()` ne trouve plus `waits[id]` (le premier l'a effacé) et remplace `cancelled[id]` par `{}`. L'événement `tell-cancelled` tardif du premier Annuler ne trouve alors aucune place pour l'agent (`page.js`, gestionnaire de `tell-cancelled`) et le toast ne dit pas « had already seen it; look at the document before you Tell again ». Classe : c (tour 5 d'Opus, note 1, GO sur le reste). Plus ancien que PR #257 : l'ancien code écrivait `undefined` à cet endroit.

**Blocked by:** none

**Claimed by:** Kian 2026-11-14 00:32

**Status:** done (PR 283, merged as 2a89ed3)

**Établi (preuves) :** `opus-round5-fix.md` de pr-23-reviews, note 1 : lecture du code, non reproduit par un test.

**Par où commencer :** ne remplacer `cancelled[id]` que si `waits[id]` existe (ou fusionner les places des deux Annuler) ; écrire un test de page qui tient l'événement du premier Annuler, double-clique Annuler, puis le libère.

- [x] Un test de page double-clique Annuler sur un Tell déjà vu et échoue sans le correctif
- [x] L'événement tardif du premier Annuler dit « had already seen it » après un deuxième Annuler
