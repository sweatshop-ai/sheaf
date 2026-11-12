# 17: Le test du toast d'annulation d'un Tell échoue de temps en temps en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_writing.py::test_a_tell_or_cancel_the_hub_cannot_be_reached_for_says_that_it_did_not_go_out[cancel-tell]`.

**Blocked by:**
- 04

**Claimed by:** Birgit 2026-11-11 12:58

**Status:** in-progress

L'attente du toast (8 s) expire. PR #241 run 42925663097 tentative 1 ; PR #240 run 42923857640 tentative 1 ; t-compute à 9aed290 (ticket 03). Pas la même cause qu'Échap (ticket 10) : le test n'appelle pas `fail_a_reply` et n'abandonne aucun envoi ; il ne se reproduit pas en local (12 passages). Le test relève maintenant le nombre de requêtes `/_/cancel` refusées, les toasts vus et le texte de la boîte (047a057) : le prochain rouge dit si le clic est perdu (0 requête) ou si le toast est remplacé (≥ 1).

- [x] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [x] Le correctif traite la cause, pas un délai ou une relance

**Cause (preuve locale, 2026-11-11).** Défaut du test. La fixture `thread` fait son premier commentaire avec Tell : le bouton `cancel-tell` est sur la page avant que le test envoie sa réponse (mesuré : 1 avant le clic). Le test clique donc Annuler pendant que l'envoi de la réponse est encore en cours ; le refus d'annulation affiche « Cancel did not go out », puis la réponse du hub arrive et son toast « Sent to your Cosima session… » prend la place. Un sondage retardé par un runner chargé ne voit plus que le second (relevé : `['', 'Cancel did not go out: …', 'Sent to your Cosima session. Its reply will appear in the thread.']`). Reproduit avec un sondage retardé de 1 s : `timed out waiting for the toast`, le message de la CI.

**Limite.** Aucune CI n'a encore relevé les toasts d'un échec : que le rouge de PR #241/#240 soit celui-ci n'est pas confirmé. Le relevé (requêtes refusées, toasts vus, texte de la boîte, 047a057) reste dans le test pour le dire.

- External: la CI doit rejouer l'échec pour confirmer que c'est celui-là (le relevé donnera la cause)

**Correctif.** Le test attend le toast de la réponse (« Sent to your ») avant de cliquer Annuler. Rouge sans cette attente avec le sondage retardé, vert avec.

**Reste.** Le toast « Sent to your » peut venir de l'envoi du premier Tell (la fixture) arrivé tard sur la page rechargée, pas de la réponse : l'attente ne prouve pas laquelle. Revue Opus du 2026-11-11 ; aucun signal fiable de « première livraison finie » dans cette fixture (le premier Tell ne passe pas par `agent.calls()`). Fenêtre étroite, non vue.

- [x] CI verte sur trois passages de suite : runs 43190504226 sur 08c8883 et 43201969936 sur 4455590, chacun vert aux tentatives 1 et 2
