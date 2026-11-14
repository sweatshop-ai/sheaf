# 121: Deux pages écrivent le stockage des envois gardés sans relecture : fenêtre prouvée, et la conception claim/repère de la PR 341

**What to build:** Corriger la perte d'une entrée quand deux pages d'un même document font échouer un envoi au même instant (ticket 97, PR 341 réduite à la preuve). Code : `commentDraftsSave` dans `src/sheafmd/page/page.js`. SPEC 10.4 écrit la limite. Le test `test_two_sends_that_fail_at_the_same_instant_on_two_pages_are_both_kept` (`tests/page/test_page_writing.py`) est `xfail(strict=True)` : le jour où le correctif arrive, il passe et devient un échec à retirer. Les deux tests de Discard (réponse, modification) passent sur main (A n'écrit rien après le Discard de B) et fixent ce comportement pour le correctif.

**La fenêtre est prouvée.** Deux pages font échouer chacune un envoi à un instant commun (une attente active jusqu'à une heure commune dans le `fetch` de chaque page). Aux 40 tours, les deux pages lisent le même stockage (441 octets) à 0,1 ms d'écart, chacune écrit sa version (421), et la dernière remet l'entrée de l'autre encore marquée `out` : la liste « not sent » la cache pendant HELD (32 s). Relire la clé juste avant d'écrire n'aide pas : la sauvegarde la relit déjà, et la vue d'une page reste périmée bien au-delà de 100 ms (une relecture 100 ms plus tard montrait encore sa propre écriture comme la dernière).

**La conception essayée (commit ff7d176, étiquette `rashid/t97-claim-mark`, présente sur origin) :** `claim()` retient 2 s ce qu'une écriture a mis ou retiré ; `reclaim()` le revérifie à chaque événement `storage` et remet ce qu'une écriture d'une autre page a défait ; `withdrawn()` pose, avant l'écriture du stockage, un repère `<clé>:gone:<entrée>` pour tout retrait voulu (Discard, Cancel, envoi pris), et `reclaim` lâche une revendication plus ancienne que le repère. Elle ferme la fenêtre du test (40 tours verts) et le Discard, mais quatre tours de revue ont trouvé quatre a/b (voir ci-dessous) : le correctif a été laissé de côté, pas jugé faux.

**Constats des tours 1, 2 et 3** (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-97-reviews/opus-round1.md`, `r2-narrow.md`, `r3-narrow.md`) :
- a1 (tour 1) : un retrait par le hub sur une page était remis par la page qui l'avait revendiqué (réponse prise puis « not sent »). Fermé par le repère.
- Discard (tour 2, Rhea) : le Discard de B moins de 2 s après l'écriture de A était remis par A (8 écritures, main : 0). Fermé par le repère.
- C1 (tour 2) : la ligne ajoutée pour a1 annulait aussi une revendication après une écriture périmée. Retirée.
- C2 (tour 2) : une écriture de repère refusée (stockage plein) sautait l'écriture du stockage. Les repères ont leur propre `try`, la purge passe d'abord.
- F1 (tour 3, classe a, rare) : un repère refusé est avalé et le retrait est écrit quand même ; si A a écrit l'entrée moins de 2 s avant, A la remet, et B réaffiche le texte écarté. Remède proposé : quand l'écriture d'un repère échoue, sauter l'écriture du stockage seulement si elle retire quelque chose.
- F2 (tour 3, d) : aucun test ne couvre l'envoi pris par le hub sur deux pages (l'envoi de A tenu, B traite le `changed` de son rid, l'envoi de A réussit, le stockage reste sans l'entrée 3 s). La fermeture de a1 ne dépend que de l'ordre dans lequel le navigateur livre le repère et le changement du stockage.
- F3 (tour 3, c) : repères écrits puis écriture du stockage refusée : les repères restent 10 s sans que le retrait ait eu lieu.

**La leçon :** l'ordre des événements `storage` entre pages est un détail interne de Chromium. Une conception qui en dépend a besoin d'un test qui montre cet ordre (par exemple, noter l'instant de l'écriture d'un repère, de l'écriture du stockage et de l'événement chez l'autre page), avant d'être jugée fermée. Deux choses de la conception sont à décider : s'appuyer sur ces événements, ou changer de support (un verrou Web Locks, ou une entrée par clé `localStorage` au lieu d'une liste unique, qui ne se réécrase pas).

**Aussi dans ce ticket** : tout le contenu du ticket 114 (restes c et d des tours 1 et 2 : c1 à c8, d1 à d4, voir `114-restes-b-c-d-de-la-pr-341-ticket-97-reclaim-des-envois-gardes.md`) concerne cette conception ; ils ne valent que si elle est reprise. Ne rien en tirer si une entrée par clé la remplace.

**Blocked by:** aucun

**Status:** ready-for-agent
