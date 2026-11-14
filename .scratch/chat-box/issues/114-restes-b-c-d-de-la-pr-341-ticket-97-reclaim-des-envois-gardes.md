# 114: Restes b, c, d de la PR 341 (ticket 97) : reclaim des envois gardés

**What to build:** Restes de la revue Opus de la PR 341, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-97-reviews/opus-round1.md`. Code : `claim()`/`reclaim()` dans `src/sheafmd/page/page.js`, près de `commentDraftsSave`.
- b3 : aucun test ne montre qu'un Discard ou un `taken` sur une autre page, moins de 2 s après l'écriture qu'il termine, reste retiré. Limite connue : A remet un Discard de B fait dans les 2 s ; décider si cela suffit ou s'il faut un signe de retrait volontaire.
- c1 : deux pages qui veulent des choses opposées pour une entrée s'écrivent tour à tour (8 fois chacune) ; sur un Discard depuis la liste ouverte, chaque tour redessine le popover où la personne vient de cliquer. `reclaims` ne se remet à zéro qu'à une écriture propre : une page qui a épuisé ses 8 ne défend plus ses autres entrées.
- c2 : la purge de `pendingClears` revendique contre un `lastRead` périmé (une lecture non stricte ratée laisse `[]`) : elle revendique toutes les entrées 2 s. Calculer `before` depuis la lecture brute de `commentDraftsSave`.
- c3 : une entrée sans `root` en reçoit une à l'écriture : la première écriture après une mise à jour les revendique toutes (même remède que c2).
- c4 : deux commentaires gardés sur le même passage, tous deux modifiés, perdent leur `rid` et partagent une clé ; avec une écriture périmée, `reclaim` écrase l'un par l'autre. Ajouter `at` à la clé des nouveaux commentaires.
- c5 : le `catch` de `reclaim` cache un `setItem` refusé sans mettre `storeOk = false`.
- d : le commentaire dit « par son passage » alors que la clé contient `rid` ; les affectations de `lastRead` dans `claim` et `reclaim` ne sont lues qu'après une relecture, sauf dans le cas c2.

**Blocked by:** PR 341 fusionnée

**Status:** ready-for-agent
