# 114: Restes b, c, d de la PR 341 (ticket 97) : reclaim des envois gardés

**What to build:** Restes de la revue Opus de la PR 341 (tours 1 et 2), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-97-reviews/opus-round1.md` et `r2-narrow.md`. Code : `claim()`/`reclaim()`/`withdrawn()` dans `src/sheafmd/page/page.js`, près de `commentDraftsSave`. Aucun b ici : les b sont corrigés dans la PR.

Classe d (tests manquants et notes) :
- d1 : pas de test pour le Discard d'un message minimisé, un Cancel de formulaire, un envoi pris par le hub (le Discard d'une réponse ou d'une modification est testé depuis la PR 341).
- d2 : le commentaire dit « par son passage » alors que la clé contient `rid` ; les affectations de `lastRead` dans `claim` et `reclaim` ne sont lues qu'après une relecture, sauf dans le cas c2.
- d4 (r3 F2) : aucun test ne couvre l'envoi pris par le hub sur deux pages : l'envoi de A tenu, B traite le `changed` de son rid, l'envoi de A réussit, le stockage reste sans l'entrée 3 s. La fermeture de a1 ne tient que par le repère.
- d3 : aucun test multi-pages n'utilise `p.clock` (voir c7).

Classe c (défauts plus petits, avec contournement) :
- c1 : deux pages qui veulent des choses opposées pour une entrée s'écrivent tour à tour (8 fois chacune) ; sur un Discard depuis la liste ouverte, chaque tour redessine le popover où la personne vient de cliquer. `reclaims` ne se remet à zéro qu'à une écriture propre : une page qui a épuisé ses 8 ne défend plus ses autres entrées.
- c2 : la purge de `pendingClears` revendique contre un `lastRead` périmé (une lecture non stricte ratée laisse `[]`) : elle revendique toutes les entrées 2 s, et pose des repères sur ce même `lastRead` (peut éteindre une revendication utile). Calculer `before` depuis la lecture brute de `commentDraftsSave`.
- c3 : une entrée sans `root` en reçoit une à l'écriture : la première écriture après une mise à jour les revendique toutes (même remède que c2).
- c4 : deux commentaires gardés sur le même passage, tous deux modifiés, perdent leur `rid` et partagent une clé ; avec une écriture périmée, `reclaim` écrase l'un par l'autre, et sans `rid` aucun repère n'est posé. Demande deux commentaires gardés modifiés sur un passage. Ajouter `at` à la clé des nouveaux commentaires.
- c5 : le `catch` de `reclaim` cache un `setItem` refusé sans mettre `storeOk = false`.
- c8 (r3 F3) : si les repères sont écrits puis l'écriture du stockage est refusée, les repères restent 10 s alors que le retrait n'a pas eu lieu : l'autre page abandonne sa revendication sur cette clé, une écriture périmée dans cette fenêtre n'est pas réparée.
- c7 : horloges factices (`p.clock`) : un repère daté du futur n'est jamais purgé par une page à l'heure réelle.

**Blocked by:** PR 341 fusionnée

**Status:** ready-for-agent