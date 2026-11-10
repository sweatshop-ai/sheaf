# 08: Menu ⋯ Edit : une réponse tapée est perdue quand le stockage refuse

**What to build:** Quand le stockage local est plein ou bloqué, ⋯ → Edit ne doit pas perdre le texte tapé dans le champ de réponse. Issu de la review du bug hunt de la PR #238 (P2 n° 2) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Status:** ready-for-agent

**Ce qui ne va pas :** `page.js:2194`. ⋯ → Edit appelle `stash()` sans lire son retour. Si `stash()` renvoie faux (stockage plein ou bloqué), l'ouverture du formulaire d'édition continue et la réponse tapée est abandonnée.

- [ ] Avec un stockage qui refuse, ⋯ → Edit garde la réponse tapée (elle reste dans le champ, ou Edit ne s'ouvre pas et le dit)
- [ ] Test avec un `stash()` qui renvoie faux, rouge avant le correctif
- [ ] Avec un stockage qui marche, comportement inchangé
- [ ] PR séparée, CI verte
