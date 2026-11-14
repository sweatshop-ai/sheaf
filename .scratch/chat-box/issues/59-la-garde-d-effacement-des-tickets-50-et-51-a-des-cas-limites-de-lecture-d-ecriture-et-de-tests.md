# 59: La garde d'effacement des tickets 50 et 51 : cinq cas limites de lecture et d'écriture du stockage, et deux points de test

**What to build:** Constats de la revue 1 de la PR 281 (tickets 50 et 51), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-50-reviews/round-1.md` (Opus, GO, aucune classe a ou b). Classe c (F1 à F5) et d (F6, F7), à décider un par un : corriger, ou écrire la limite dans le SPEC.
- F1 (c) : `commentDraftsLoad` non strict peut maintenant lever, parce que l'écriture de purge exécute `unsentLine()` (page.js ~1566, 1588) ; dans les appelants stricts (1575, 1643) cette levée est prise pour une lecture refusée : `storeOk` faux et un effacement gardé alors que le stockage répond.
- F2 (c) : une lecture qui purge un effacement gardé peut redessiner ou fermer la liste « not sent » (`closePopover` / `showUnsent`, 1771, 1783) pendant que l'appelant travaille (ex. `keptThreadForm`, 2339, depuis « Open the thread »).
- F3 (c) : lecture puis écriture non atomiques entre onglets (1553 et 1582) : une entrée écrite par un autre onglet entre les deux lectures serait perdue ; ne se produit pas en pratique (une seule tâche), même forme que tous les écrivains existants.
- F4 (c) : stockage plein (`setItem` refusé, `getItem` répond) : l'effacement reste gardé et chaque lecture suivante réessaie l'écriture et met `storeOk` à faux ; le prédicat tenu peut cacher puis effacer une entrée sans id écrite par un autre onglet (1587, 1623).
- F5 (c) : la purge ne part que dans une lecture ; un rechargement avant toute lecture ramène l'entrée une fois (limite déjà dite par la décision du ticket 51).
- F6 (d) : la purge écrit la liste filtrée de `commentDraftsRaw` et supprime donc les entrées mal formées (1547-1549), déclenchée par une lecture et non par la personne ; même comportement que toute écriture.
- F7 (d) : les deux tests du ticket 50 gardent `wait_for_timeout(500)` et `wait_for_timeout(300)` : sous charge le stockage peut déjà être relisible et le chemin tenu n'est pas exercé (faux vert) ; remplacer par un signal positif, comme le troisième test (`until(... stored_drafts ...)`).
Classe : c, d.

**Décisions (Rhea, 2026-11-14) :**
- F1 : corrigé. L'écriture de purge ne dessine plus la ligne dans la lecture (`commentDraftsSave(held, true)` la dessine dans un minuteur de 0 ms) : une levée n'est plus prise pour une lecture refusée et ne sort plus d'une lecture non stricte. Test rouge d'abord.
- F2 : corrigé par le même geste (la ligne et la liste sont redessinées quand l'appelant a fini) ; peu coûteux, sans perte de donnée. Le test compte les redessins faits dans une lecture (zéro attendu).
- F3 : limite écrite dans le SPEC (lecture puis écriture non atomiques entre onglets, même forme que tout écrivain).
- F4 : limite écrite dans le SPEC (stockage plein) ; pas de correctif d'une ligne, pas de test.
- F5 : limite déjà dite par la décision du ticket 51 ; le SPEC y renvoie.
- F6 : gardé ; une purge écrit la liste filtrée, comme toute écriture ; écrit dans le SPEC.
- F7 : corrigé. Les deux tests du ticket 50 attendent un signal positif (une lecture refusée est vue, l'entrée est encore dans le stockage, puis le stockage se vide) au lieu de `wait_for_timeout`.

**Blocked by:** none

**Claimed by:** Imani 2026-11-14

**Status:** in-progress

**Par où commencer :** F7 d'abord (tests sans attente fixe, sur t-compute, pas sur le portable), puis F1 : un test où `unsentLine` lève pendant la purge. Pour F2 à F5, décider avec le propriétaire du SPEC s'il s'agit d'une limite à écrire ou d'un correctif.

- [x] F1 : une levée de `unsentLine` dans la purge ne passe ni pour une lecture refusée ni ne sort d'une lecture non stricte — test, rouge avant
- [x] F2 à F5 : décision écrite par cas (corriger ou limite dans le SPEC)
- [x] F6 : décision écrite (garder ou ne pas supprimer les entrées mal formées dans une purge)
- [x] F7 : les deux tests du ticket 50 n'attendent plus un temps fixe : ils prouvent que le chemin tenu est exercé
