# 22: La page peut afficher une réponse déjà reçue jusqu'à 10 s en retard derrière une longue écriture

**What to build:** Quand une vérification du document (`checkText`) est en cours, la page garde l'événement `changed` d'une écriture jusqu'à la réponse de cette vérification ou jusqu'à `CHECK_WAIT` (10 s). Si la vérification attend le verrou d'une écriture très longue (rendu d'un grand document), la réponse déjà reçue dans l'événement s'affiche jusqu'à 10 s en retard. Trouvé en diagnostiquant le ticket 20.

**Blocked by:**
- 04

**Status:** ready-for-agent

Rien n'est perdu : le fichier a la réponse, le stockage de la page est vidé à l'arrivée de l'événement (`taken`), et l'affichage suit à la fin de la vérification ou de `CHECK_WAIT`. Le retard est borné. Le ticket 20 l'a mis hors du test (l'horloge de la page avance de `CHECK_WAIT`) sans changer la page. À décider avant de coder : si l'événement qui porte déjà la réponse doit attendre une vérification dont le verrou est celui de son propre écrivain.

- [ ] Décision écrite (garder l'attente, ou appliquer l'événement sans attendre la vérification), avec un test rouge puis vert si la page change
