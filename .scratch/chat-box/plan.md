# Boîte de chat des commentaires sheaf : décisions et plan de travail

Cette page reprend tout ce qui a été décidé pour transformer la fenêtre de commentaire de sheaf en vraie boîte de chat, et ce qu'il reste à faire. À la fin, on sait comment la boîte doit se comporter et dans quel ordre les six tickets arrivent.

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

## Les six tickets et leur ordre

| N° | Ticket | Bloqué par | Statut |
|---|---|---|---|
| 01 | Le fil en boîte de chat : champ ouvert, bandeau, texte gardé | Rien | En cours |
| 02 | La sélection ouvre la boîte, bascule Comment / Edit, Ctrl+C | 01 | En cours |
| 03 | La barre mobile, essayée sur l'iPhone | 02 | À faire |
| 04 | Livrer la boîte : review, CI, fusion | 01, 02, 03 | À faire |
| 05 | Les blocs à copier | 04 | À faire |
| 06 | Le micro dans la boîte | 04 | À faire |

## Ce qui reste ouvert

- **Transcription sur un hub local :** sans Open WebUI, il faudra décider d'où elle vient. La question se posera au ticket 06.
- **Arrivée sur tiroir-tt :** elle passe par une montée de version du hub, faite par le track action-list après la fusion du ticket 04.
