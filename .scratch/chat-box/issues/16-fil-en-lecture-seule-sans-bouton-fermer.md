# 16: Un fil en lecture seule n'a pas de bouton Fermer

**What to build:** Sur une page en lecture seule (`CFG.readonly`) qui a des commentaires, la boîte d'un fil doit garder le × Close : fermer ne demande aucun droit d'écriture. Issu de la revue Codex de la fusion cdb0e24 (c562fc1..cdb0e24), trouvaille P2 n° 3.

**Blocked by:** 04

**Claimed by:** Emil 2026-11-11 11:19

**Status:** in-progress

**Ce qui ne va pas :** `page.js:1800-1804` (`bandHtml`). Quand `canSave` est faux, le test `!canSave ? '' : (...)` retire en bloc le menu ⋯, Resolve et Close. Le fil s'ouvre pourtant, mais n'a plus de ×. Close (`data-a="minimize"`) doit être rendu et branché indépendamment de Resolve, Reopen, Edit et Delete. À vérifier au passage : que la boîte se ferme encore par Échap et un clic à côté en lecture seule.

- [ ] Page en lecture seule, fil ouvert : le × Close est là et ferme la boîte
- [ ] Resolve, Reopen, Edit et Delete restent absents en lecture seule
- [ ] Test rouge avant le correctif
- [ ] PR séparée, CI verte
