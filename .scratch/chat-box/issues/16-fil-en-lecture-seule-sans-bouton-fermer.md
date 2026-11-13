# 16: Un fil en lecture seule n'a pas de bouton Fermer

**What to build:** Sur une page en lecture seule (`CFG.readonly`) qui a des commentaires, la boîte d'un fil doit garder le × Close : fermer ne demande aucun droit d'écriture. Issu de la revue Codex de la fusion cdb0e24 (c562fc1..cdb0e24), trouvaille P2 n° 3.

**Blocked by:** 04

**Claimed by:** Isolde 2026-11-12 10:14

**Status:** done (PR 245, merged as 81afdff)

**Ce qui ne va pas :** `page.js:1800-1804` (`bandHtml`). Quand `canSave` est faux, le test `!canSave ? '' : (...)` retire en bloc le menu ⋯, Resolve et Close. Le fil s'ouvre pourtant, mais n'a plus de ×. Close (`data-a="minimize"`) doit être rendu et branché indépendamment de Resolve, Reopen, Edit et Delete. À vérifier au passage : que la boîte se ferme encore par Échap et un clic à côté en lecture seule.

- [x] Page en lecture seule, fil ouvert : le × Close est là et ferme la boîte — test_a_thread_on_a_page_that_cannot_save_keeps_the_cross_and_no_write_control (0967137, b1b3f24)
- [x] Resolve, Reopen, Edit et Delete restent absents en lecture seule — same test: Resolve, Reopen, Edit, Delete count 0; Escape and a click beside the box close it
- [x] Test rouge avant le correctif — red: 'no Close on a thread that cannot save' before the fix (0967137)
- [x] PR séparée, CI verte — PR #245 : run 43213637076 sur la tête 3830124 (3/3 tranches vertes), et sur main run 43219154279 sur 81afdff (3/3)
