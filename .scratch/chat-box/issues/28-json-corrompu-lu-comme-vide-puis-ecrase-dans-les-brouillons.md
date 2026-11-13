# 28: une valeur JSON corrompue dans la clé des brouillons est lue comme vide puis écrasée

**What to build:** Distinguer « illisible » de « vide » aussi quand `JSON.parse` lève dans `commentDraftsRaw`: ne pas l'écraser sans le dire (ou la mettre de côté sous une autre clé).

**Blocked by:** none

**Claimed by:** Amaia 2026-11-12 23:03

**Status:** done (PR 262, merged 0ebf621)

**Ce qui ne va pas :** `page.js` ~1496 : une valeur corrompue rend `[]` et la sauvegarde suivante l'écrase. Le ticket 21 ne couvre que `getItem`. Issu de la revue Opus du PR 250 (ticket 21), trouvaille P2 mise de côté (cas rare, aucune perte de texte tapé).

- [x] une valeur non JSON dans la clé : le comportement choisi est écrit, testé, et rien n'est perdu sans que la page le dise
