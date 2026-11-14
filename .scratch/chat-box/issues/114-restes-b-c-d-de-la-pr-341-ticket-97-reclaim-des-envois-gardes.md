# 114: Restes b, c, d de la PR 341 (ticket 97) : reclaim des envois gardés

**What to build:** Restes de la revue Opus de la PR 341, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-97-reviews/opus-round1.md`. Code : `claim()`/`reclaim()` dans `src/sheafmd/page/page.js`, près de `commentDraftsSave`.
- b3 : le Discard d'un envoi (réponse ou modification) sur une autre page est couvert depuis la PR 341 (repère `:gone:`). Pas de test pour le Discard d'un message minimisé, un Cancel de formulaire, un envoi pris par le hub.
- c1 : deux pages qui veulent des choses opposées pour une entrée s'écrivent tour à tour (8 fois chacune) ; sur un Discard depuis la liste ouverte, chaque tour redessine le popover où la personne vient de cliquer. `reclaims` ne se remet à zéro qu'à une écriture propre : une page qui a épuisé ses 8 ne défend plus ses autres entrées.
- c2 : la purge de `pendingClears` revendique contre un `lastRead` périmé (une lecture non stricte ratée laisse `[]`) : elle revendique toutes les entrées 2 s. Calculer `before` depuis la lecture brute de `commentDraftsSave`.
- c3 : une entrée sans `root` en reçoit une à l'écriture : la première écriture après une mise à jour les revendique toutes (même remède que c2).
- c4 : deux commentaires gardés sur le même passage, tous deux modifiés, perdent leur `rid` et partagent une clé ; avec une écriture périmée, `reclaim` écrase l'un par l'autre. Ajouter `at` à la clé des nouveaux commentaires.
- c5 : le `catch` de `reclaim` cache un `setItem` refusé sans mettre `storeOk = false`.
- d : le commentaire dit « par son passage » alors que la clé contient `rid` ; les affectations de `lastRead` dans `claim` et `reclaim` ne sont lues qu'après une relecture, sauf dans le cas c2.

- r2-C3 : la purge de `pendingClears` pose des repères contre un `lastRead` périmé : peut éteindre une revendication utile.
- r2-C4 : collisions de clé (c4) ; deux messages neufs sans `rid` sur le même passage : pas de repère, l'entrée restante est écrasée. Ajouter `at` à la clé.
- r2-C5 : horloges factices (`p.clock`) : un repère daté du futur n'est jamais purgé par une page à l'heure réelle ; aucun test multi-pages actuel n'en utilise.

**Blocked by:** PR 341 fusionnée

**Status:** ready-for-agent