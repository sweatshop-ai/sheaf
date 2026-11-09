# 02: La sélection ouvre la boîte, bascule Comment / Edit, Ctrl+C

**What to build:** Sur desktop, en mode Comment, sélectionner du texte ouvre directement la boîte, le curseur dans le champ, sans passer par le bouton Comment. Une bascule Comment / Edit toujours visible près du menu rond rend le mode évident ; en Edit, une sélection ne fait que sélectionner. Les numéros ouvrent le fil dans les deux modes et la touche E bascule aussi. Tant que le champ est vide, Ctrl+C copie le passage sélectionné.

Le code est déjà sur la branche `cleo/chat-box` ; ce ticket finit le travail en adaptant les anciens tests.

**Blocked by:** 01 (les deux partagent l'aide de test qui crée un commentaire)

**Status:** in-progress

- [ ] Les anciens tests de sélection décrivent l'ouverture directe ; une sélection refusée garde son bouton grisé avec la raison
- [ ] Après l'ouverture, la boîte ne se referme pas sur le clic qui suit la sélection
- [ ] Le passage reste marqué dans le texte tant que la boîte est ouverte
- [ ] Ctrl+C essayé pour de vrai dans un navigateur, pas seulement simulé
- [ ] La page montée dans tiroir garde la bascule et l'ouverture directe
- [ ] La spec décrit ce comportement
