# 01: Le fil en boîte de chat : champ ouvert, bandeau, texte gardé

**What to build:** Ouvrir un fil montre une boîte de chat étroite, avec le curseur déjà dans le champ, sur desktop comme sur téléphone. Le bandeau du haut porte le passage cité, Minimize et Fermer. Minimize, Échap et un clic à côté ferment la boîte et gardent le texte ; il revient en cliquant sur le numéro, même après un rechargement. Fermer résout le fil, et un texte non envoyé part dans la liste « not sent ». Entrée envoie à l'agent, Maj+Entrée va à la ligne, et sans agent connecté le message reste un commentaire avec une ligne qui l'explique.

Le code est déjà sur la branche `cleo/chat-box` ; ce ticket finit le travail en adaptant les anciens tests au nouveau contrat.

**Blocked by:** None (can start immediately)

**Claimed by:** Suraya 2026-11-09 16:18

**Status:** in-progress

- [ ] Les anciens tests du formulaire décrivent le nouveau contrat : un champ vide n'est pas « en train d'écrire », un texte tapé est gardé au lieu de bloquer la fermeture, il n'y a plus de Cancel sauf pour Edit
- [ ] Un rechargement nécessaire n'est retenu que par un texte tapé, jamais par le champ vide
- [ ] La liste « not sent » nomme correctement un message sans numéro (aujourd'hui « 1 reply »)
- [ ] Sur un fil résolu, × ferme simplement et Reopen est dans le menu ⋯ ; Edit et Delete y sont pour ses propres messages
- [ ] Le fil s'ouvre sur son dernier message et défile vers le haut
- [ ] La spec décrit ce comportement
