# 22: La page peut afficher une réponse déjà reçue jusqu'à 10 s en retard derrière une longue écriture

**What to build:** Quand une vérification du document (`checkText`) est en cours, la page garde l'événement `changed` d'une écriture jusqu'à la réponse de cette vérification ou jusqu'à `CHECK_WAIT` (10 s). Si la vérification attend le verrou d'une écriture très longue (rendu d'un grand document), la réponse déjà reçue dans l'événement s'affiche jusqu'à 10 s en retard. Trouvé en diagnostiquant le ticket 20.

**Blocked by:**
- 04

**Status:** done (décision) — garder l'attente (Rhea, 2026-11-14)

Rien n'est perdu : le fichier a la réponse, le stockage de la page est vidé à l'arrivée de l'événement (`taken`), et l'affichage suit à la fin de la vérification ou de `CHECK_WAIT`. Le retard est borné. Le ticket 20 l'a mis hors du test (l'horloge de la page avance de `CHECK_WAIT`) sans changer la page. À décider avant de coder : si l'événement qui porte déjà la réponse doit attendre une vérification dont le verrou est celui de son propre écrivain.

**Décision (Rhea, 2026-11-14, sur la proposition d'Amaia) : garder l'attente.** Le retard est borné à 10 s et ne se produit que derrière une écriture de plus de 30 s (la vérification attend le verrou de l'écrivain) ; aucune donnée n'est perdue (le fichier a la réponse). `heardAfterCheck` protège d'un `changed` du fichier d'un autre dossier sous la même adresse, qui ferait recharger la page dedans. Alternative décrite pour plus tard : appliquer sans attendre un événement qui nomme un identifiant de requête que cette page a envoyé (il est le sien par construction) ; c'est un changement de l'ordre des événements de page.js, à faire dans sa propre PR avec un test rouge d'abord. À noter : le ticket 61 n'est pas un cas de cette attente (sa cause est une lecture unique du test, PR 299) ; l'attente de 10 s n'a été vue que dans le test du ticket 20.

- [x] Décision écrite (garder l'attente, ou appliquer l'événement sans attendre la vérification), avec un test rouge puis vert si la page change
