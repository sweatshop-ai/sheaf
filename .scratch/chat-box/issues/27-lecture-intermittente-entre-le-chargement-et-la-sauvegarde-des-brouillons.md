# 27: une lecture du stockage qui échoue une fois puis réussit vide encore les brouillons de la page

**What to build:** Les écrivains (`draftsReplace`, `threadKeep`, `taken`) construisent leur liste avec `commentDraftsLoad`, qui lit sans `strict`; ne rien écrire si cette première lecture est refusée.

**Blocked by:**
- External: PR 250 (ticket 21) merged into main

**Claimed by:** 

**Status:** ready-for-agent

**Ce qui ne va pas :** `page.js` ~1495-1502 et 1518, 1544, 1560 : si le premier `getItem` lève et que celui de `commentDraftsSave` réussit, la liste vient de `[]`, l'écriture ne garde que les entrées d'autres racines plus la nouvelle, et `storeOk` reste vrai. Il faut un `getItem` qui échoue par intermittence (un refus durable ne l'atteint pas). Issu de la revue Opus du PR 250 (ticket 21), trouvaille P2 mise de côté (cas rare, aucune perte de texte tapé).

- [ ] un `getItem` qui lève la première fois puis réussit : aucun brouillon de cette page n'est perdu à l'écriture suivante, test rouge avant le correctif
