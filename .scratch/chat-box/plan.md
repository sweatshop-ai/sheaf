# Boîte de chat des commentaires sheaf : décisions et plan de travail

Cette page reprend tout ce qui a été décidé pour transformer la fenêtre de commentaire de sheaf en vraie boîte de chat, et ce qu'il reste à faire. À la fin, on sait comment la boîte doit se comporter et dans quel ordre les tickets arrivent.

## Où en est le travail au 9 novembre 2026

- Le code est sur la branche `cleo/chat-box` du dépôt `sweatshop-ai/sheaf`, à partir de `main` (`c562fc1`).
- Les 15 tests de la boîte passent. Les anciens tests de la page ne sont pas encore adaptés : aucun résultat complet n'existe à ce jour.
- La page d'essai tourne sur un hub séparé, sans toucher au sheaf habituel.

## Pourquoi on reproduit l'aspect d'Open WebUI au lieu de réutiliser son composant

Le composant du chat d'Open WebUI ne peut pas être branché dans sheaf. Il fait 3 164 lignes et 71 imports, il dépend de leurs modèles, fichiers, terminal et de 19 stores, et il n'est pas exporté par leur build. Intégrer leur chat tel quel enverrait les messages à leurs modèles, pas à la session de l'agent.

La boîte reprend donc leur composition : grand cadre arrondi, texte en haut, rond noir avec la flèche. Le code n'est pas copié, car leur licence impose de garder leur marque. Ce qui se réutilise vraiment est leur service de transcription, pour le micro.

## Comment la boîte de chat doit se comporter

| Sujet | Décision |
|---|---|
| Rôle de la boîte | Une seule action : parler à l'agent |
| Envoi | Entrée envoie à l'agent, Maj+Entrée va à la ligne, la flèche envoie aussi |
| Sans agent connecté | Le message reste un commentaire ; aucune ligne sous le champ (le menu dit pourquoi) |
| Forme | Étroite et verticale, sur desktop comme sur mobile ; bulles, mes messages à droite |
| Défilement | Le fil s'ouvre sur le dernier message et défile vers le haut |
| Curseur | Déjà dans le champ à l'ouverture, sur desktop et sur téléphone |
| Sélection sur desktop | En mode Comment, la boîte s'ouvre directement |
| Sélection sur téléphone | Appui long = un mot, appui long + glisser = une phrase (choix de Thierry, 2026-11-10) ; au relâchement du doigt la boîte s'ouvre, le curseur dans le champ, dans cet événement ; pas de poignées à déplacer après coup, ni de menu Copier natif ; le délai de 600 ms n'ouvre rien tant qu'un doigt est posé ; un toucher à côté d'une sélection n'ouvre rien ; la barre ne reste que pour une sélection refusée ; en repli, un toucher dans la zone vide de la boîte met le curseur dans le champ |
| Copier | Avec le champ vide, Ctrl+C copie le passage sélectionné ; sur téléphone la boîte s'ouvre à la place du menu Copier, la citation de la boîte reste |
| Modes | Un seul bouton à bascule toujours visible : « Edit (E) » en mode Comment, « Save (Ctrl+S) » en mode Edit (« Edit » et « Save » au toucher), même taille, bord de la couleur de la boule d'état (gris, vert, rouge) ; Save enregistre puis revient en mode Comment, et reste en Edit si l'enregistrement échoue ; en Edit, une sélection reste une sélection |

## Ce que font les boutons du bandeau et du menu

| Contrôle | Info-bulle | Effet |
|---|---|---|
| × | Close | Ferme la boîte et garde tout ; même effet qu'Échap ou un clic à côté ; sur un fil ouvert, un fil résolu et un nouveau message |
| − sur un fil ouvert | Resolve | Résout le fil ; un texte non envoyé part dans la liste « not sent ». Absent sur un fil résolu et sur un nouveau message (Reopen reste dans ⋯) |
| ⋯ | More | Edit et Delete sur ses propres messages, Reopen sur un fil résolu |

## Les blocs à copier pour un mail, un titre ou un prompt

L'agent sait quand un texte est fait pour être copié. Il l'écrit dans un bloc citation marqué `> [!COPY]`, affiché comme une citation modifiable avec un bouton Copier. Cette fonction arrive dans une PR séparée, après la boîte.

## Les tickets et leur ordre

| N° | Ticket | Bloqué par | Statut |
|---|---|---|---|
| 01 | Le fil en boîte de chat : champ ouvert, bandeau, texte gardé | Rien | Fait |
| 02 | La sélection ouvre la boîte, bascule Comment / Edit, Ctrl+C | 01 | Fait |
| 03 | La barre mobile, essayée sur l'iPhone | 02 | Fait |
| 04 | Livrer la boîte : review, CI, fusion | 01, 02, 03 | Fait |
| 05 | Les blocs à copier | 04 | Fait (PR #240 fusionnée dans main 2883104, CI de main verte, run 43198417261 ; hub du portable sur 2883104) |
| 06 | Le micro dans la boîte | Rien | À faire |
| 07 | Page montée : un toucher dans la zone vide de la boîte met le curseur dans le champ | 04 | Fait |
| 08 | Menu ⋯ Edit : une réponse tapée est perdue quand le stockage refuse | 04 | Fait |
| 09 | Menu ⋯ Edit : les changements d'un formulaire d'édition déjà modifié sont perdus | 04 | Fait |
| 10 | Le test d'Échap échoue de temps en temps en CI : trouver la cause | Rien | Fait (fix 047a057, on main via 7dae7b2 (PR 241) |
| 11 | fillPopover ramène le curseur dans le premier formulaire | 04 | Fait |
| 12 | Revue Codex de la fusion cdb0e24 | Rien | Fait |
| 13 | Bloc à copier : une ligne qui ouvre un bloc HTML avant `---` rend le bloc en citation simple | Rien | Fait (PR 289, merge 5767d19) |
| 14 | Un brouillon réduit dont on vide le champ reste dans le stockage | 04 | Fait (PR 245, merged as 81afdff) |
| 15 | La liste « not sent » est calculée avant que la boîte ouverte y mette son texte | 04 | Fait (PR 245, merged as 81afdff) |
| 16 | Un fil en lecture seule n'a pas de bouton Fermer | 04 | Fait (PR 245, merged as 81afdff) |
| 17 | Le test du toast d'annulation d'un Tell échoue de temps en temps en CI | Rien | Fait (PR 244, merged as 3a04cb2) |
| 18 | La ligne « vu » d'un Tell en attente n'arrive pas, de temps en temps, en CI | Rien | Fait (PR 244, merged as 3a04cb2) |
| 19 | Le test « envoyer et Tell » lit le fichier avant d'y trouver la réponse, de temps en temps en CI | Rien | Fait (PR 244, merged as 3a04cb2) |
| 20 | La réponse que le hub a prise n'apparaît pas dans la boîte quand la page abandonne l'envoi, de temps en temps en CI | Rien | Fait (PR 244, merged as 3a04cb2) |
| 21 | draftsReplace lit une lecture refusée comme vide | 04 | Fait |
| 22 | La page peut afficher une réponse déjà reçue jusqu'à 10 s en retard derrière une longue écriture | Rien | À faire |
| 23 | Les événements « vu » et « annulé » d'un Tell ne nomment pas l'agent : un fil qui attend deux agents les confond | Rien | En cours |
| 24 | Le test du « moins » lit la valeur d'un champ que la boîte vient de fermer, de temps en temps en CI | Rien | En cours |
| 25 | Le test « réponse à un fil supprimé revenue dans la boîte d'un nouveau commentaire » dort 300 ms au lieu d'attendre | 04 | Fait (PR 254, merged 9b6a313) |
| 26 | Après l'envoi d'un message, le fil remonte tout en haut au lieu de rester en bas | 04 | Fait (PR 249 fusionnée par Thierry, main 633d8ea, 2026-11-12) |
| 27 | une lecture du stockage qui échoue une fois puis réussit vide encore les brouillons de la page | Rien | Fait (PR 262, merged 0ebf621) |
| 28 | une valeur JSON corrompue dans la clé des brouillons est lue comme vide puis écrasée | Rien | Fait (PR 262, merged 0ebf621) |
| 29 | une boîte de nouveau commentaire au champ vidé ne se ferme plus quand le stockage refuse la lecture | Rien | Fait (PR 250 merged by Thierry, main 05a995b) |
| 30 | un brouillon que l'utilisateur a vidé pendant une lecture refusée revient quand la lecture réussit | Rien | Fait (PR 263, merged 1c4f333) |
| 31 | Le test « une réponse d'action met fin à l'attente » lit la ligne d'attente pendant une navigation de la page, de temps en temps en CI | 04 | Fait (PR 255, merged 41678e3) |
| 32 | Le hub écrit deux lignes `push-failed` pour une sauvegarde dont le dépôt distant est absent, de temps en temps en CI | Rien | Fait |
| 33 | `transcribe.py` `_key` ferme deux fois le descripteur si `os.close` échoue sur un fichier qui n'est pas régulier | Rien | Fait (PR 266, merged 5086148) |
| 34 | Le champ `proxy` de `Who` n'est lu nulle part, et aucun test ne fixe `_for_members` pour la route de dictée | Rien | Fait (PR 266, merged 5086148) |
| 35 | Les hubs construits hors de la fixture `hub` ne règlent pas leur pusher à la fin du test, et une ligne `push-failed` peut tomber dans le test suivant | 32 | Fait (PR 256, merged 302211e) |
| 36 | La limite de 30 s du relais de dictée ne couvre ni la résolution du nom ni l'établissement de la connexion | Rien | Fait (PR 272, merged b45caf3) |
| 37 | Le `Timer` de `_call` (dictée) peut encore être dans `cut()` quand `_call` rend la main | Rien | Fait (PR 272, merged b45caf3) |
| 38 | `tests/test_isolation.py::test_the_hub_that_test_started_was_stopped_when_it_ended` échoue de temps en temps en CI | Rien | Fait (PR 253 merged by Thierry, main 3b7a6cc; main CI run 43281135217 3/3 green; PR runs 43247947522 attempts 1 and 2 (6bad373), 43278368964 (35fb054) |
| 39 | Le groupe xdist des fichiers `IN_ORDER` repose sur deux internes de xdist, et `pytest-xdist>=3.6` n'a pas de borne haute | Rien | Fait (PR 258, merged 0455284) |
| 40 | `waiting.take` publie `tell-seen` avant d'écrire `tells.json`, et l'instantané des attentes lit le fichier sans le verrou | Rien | Fait (PR 280, merge 062f3a5) |
| 41 | Le nom de l'agent dans les événements d'un Tell ne concorde pas avec `tell-queued` après un renommage, ni pour une ligne écrite avant le ticket 23 | Rien | Fait (PR 280, merge 062f3a5) |
| 42 | Le résumé d'annulation de la page (`cancelNote`) est global : deux annulations à moins de 60 ms se fondent en un seul toast | Rien | Fait (PR 283, merged as 2a89ed3) |
| 43 | La page jette sans signe ce qui est tapé pendant qu'une sauvegarde n'a pas de réponse (`beforeinput` annulé quand `saving // settling`) | Rien | Fait (PR 259, merged 38ae6bf) |
| 44 | Sur une page montée, `dictOff` est perdu à chaque remontage : un micro refusé ou un service perdu fait échouer un appui de plus par remontage | Rien | À faire |
| 45 | Fermer la boîte pendant l'invite d'autorisation du micro bloque tous les boutons micro jusqu'à la réponse de la personne | Rien | À faire |
| 46 | Une touche refusée pendant une sauvegarde dans un `textarea` ou un `input` de `main` est dite par le toast mais ne laisse aucune marque | Rien | Fait (PR 287, merge 050b878) |
| 47 | Quand le pilote Playwright de la session se fige, chaque test de page suivant attend ses 300 s, et le job va jusqu'à ses 60 min sans rien nommer | Rien | Fait |
| 48 | Un deuxième Annuler pendant que la requête du premier est en route remplace les places gardées du premier par `{}` : l'événement tardif du premier ne dit plus « had already seen it » | Rien | Fait (PR 283, merged as 2a89ed3) |
| 49 | Le test « un document déjà ouvert dans un onglet n'est pas rouvert » échoue en CI sans dire pourquoi le premier `sheaf open` n'a pas ouvert de navigateur | Rien | Fait (PR 264 merged by Thierry, main 4e35ed7) |
| 50 | `threadKeep` et `taken()` perdent un effacement quand la lecture du stockage est refusée : une réponse que le hub a prise peut redevenir « not sent » et inviter un doublon | Rien | Fait (PR 281 merged as 76284b4) |
| 51 | L'effacement gardé en mémoire par le ticket 30 ne quitte le stockage qu'avec la prochaine écriture : un rechargement avant elle, ou un autre onglet, offre de nouveau l'entrée vidée | Rien | Fait (PR 281 merged as 76284b4) |
| 52 | Le test de la case tapée dans un bloc dont la sauvegarde est fusionnée échoue après 53 s, puis le pilote Playwright ne répond plus | Rien | Bloqué (PR 267 + next sighting) |
| 53 | Un test de page qui lit le toast pendant un rechargement échoue quand la machine est chargée | Rien | Fait (PR 268, merged acd42cb) |
| 54 | Le test d'un commentaire répondu pendant l'annulation attend un cochage qui n'arrive pas quand la machine est chargée | Rien | Fait (PR 269, merged cef6f06) |
| 55 | Un commentaire sur des mots d'un titre écrit son bloc au milieu du titre, et les autres lecteurs du fichier ne retrouvent plus le titre | Rien | Fait (PR 271 merged by Rhea, main 8f285ad) |
| 56 | Dans un titre où un mot se répète (`## A and A`), la page surligne la dernière occurrence avant l'ancre, pas celle qui a été choisie | Rien | Fait (PR 285, merge d9a969b) |
| 57 | Un commentaire sur des mots d'une cellule de tableau écrit son bloc au milieu de la cellule | Rien | Fait (PR 288, merged fd23dee) |
| 58 | Titres à cas limites : un titre avec espace insécable après les `#` fait planter `add_comment`, et trois cas voisins | Rien | Fait (PR 285, merge d9a969b) |
| 59 | La garde d'effacement des tickets 50 et 51 : cinq cas limites de lecture et d'écriture du stockage, et deux points de test | Rien | À faire |
| 60 | Restes de la revue Opus de la PR 280 : l'instantané lu puis publié sans verrou, le journal écrit avant le fichier, le remplissage de `agent` | Rien | À faire |
| 61 | Le test d'une réponse abandonnée que le hub a prise lit la boîte une seule fois, sans attendre que la réponse y soit : instable en CI, deux fois sur main | Rien | À faire |
| 62 | Un seul élément de toast : le toast du deuxième fil remplace celui du premier ; et deux tests de la PR 283 prouvent moins qu'ils ne disent | Rien | À faire |
| 63 | Dictée (API standard) : finitions du relais de transcription, suites de la revue Opus 1 de la PR 284 | Rien | À faire |
| 64 | Le test « ouvrir le fil sur la deuxième de deux réponses gardées » échoue de temps en temps en CI | Rien | À faire |
| 65 | Titres : une régression sur les titres faits de dièses, et finitions, suites de la revue Opus 1 de la PR 285 | Rien | En cours |
| 66 | Titres : un balayage quadratique et un accent grave dans un commentaire fermé, restes de la revue Opus 1 de la PR 286 | Rien | À faire |
| 67 | Une touche refusée dans un bloc `contenteditable` imbriqué n'a pas de marque, et les restes de la revue Opus 3 de la PR 287 | Rien | Fait (PR 292, merge cc24fe5) |
| 68 | Cellules de tableau : `<!-->` refusé, le merge sur un dernier rang sans `|` final, et trois cas que `parse` ou le découpeur de blocs lisent autrement que pandoc, restes des revues Opus de la PR 288 | Rien | À faire |
| 69 | Bloc à copier : `<![CDATA[` insensible à la casse, colonnes de tabulation et commentaire de `is_copy_block`, restes de la revue Opus 1 de la PR 289 | Rien | À faire |
| 70 | Sanitiseur : `-webkit-user-modify` en mode simple, un cas de test et une ligne de commentaire, restes de la revue Opus 1 de la PR 292 | Rien | À faire |

## Ce qui reste ouvert

- **Transcription sur un hub local :** sans Open WebUI, il faudra décider d'où elle vient. La question se posera au ticket 06.
- **Arrivée sur tiroir-tt :** elle passe par une montée de version du hub, faite par le track action-list après la fusion du ticket 04.
