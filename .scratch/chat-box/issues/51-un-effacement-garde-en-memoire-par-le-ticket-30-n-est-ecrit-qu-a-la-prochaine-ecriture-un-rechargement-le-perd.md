# 51: L'effacement gardé en mémoire par le ticket 30 ne quitte le stockage qu'avec la prochaine écriture : un rechargement avant elle, ou un autre onglet, offre de nouveau l'entrée vidée

**What to build:** Depuis le ticket 30 (PR 263), un champ de nouveau message vidé pendant une lecture refusée garde son effacement dans `pendingClears` (une variable de la page). Les lectures de la page l'écartent ; l'entrée ne part du stockage qu'avec la prochaine écriture qui aboutit (`commentDraftsSave`). Si la personne recharge ou ferme l'onglet avant toute écriture, `pendingClears` disparaît, l'entrée est toujours dans le stockage et revient dans la boîte ; un autre onglet la lit sans filtre et l'affiche comme « not sent ». Le texte du ticket 30 disait « l'appliquer à la prochaine lecture réussie ». Le ticket demande de **décider** : (a) écrire l'effacement dès la première lecture stricte qui aboutit alors que `pendingClears` n'est pas vide (écrire la liste filtrée), (b) le laisser comme il est et dire dans le SPEC que l'effacement tient « tant que la page reste ouverte et jusqu'à sa prochaine écriture ».

**Blocked by:**
- External: PR 263 (ticket 30) merged into main

**Établi (preuves) :** revue Opus de la PR 263 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-30-reviews/opus-fallback.md`, P2, scénarios A, B et C) et revue de spec (`standards.md`, « Partial »). Non reproduit par un test.

**Par où commencer :** un test de page qui vide le champ pendant une lecture refusée, rétablit la lecture, recharge la page sans rien écrire d'autre, rouvre la boîte et vérifie que le champ est vide. Il échoue tant que l'effacement n'est qu'en mémoire. Attention au scénario C : l'effacement après un envoi réussi est suivi de `reloadNow`.

- [ ] La décision (a ou b) est écrite dans le ticket avant le code
- [ ] Si (a) : un test de page échoue tant qu'un rechargement avant toute autre écriture fait revenir l'entrée vidée

**Status:** blocked (PR 263)
