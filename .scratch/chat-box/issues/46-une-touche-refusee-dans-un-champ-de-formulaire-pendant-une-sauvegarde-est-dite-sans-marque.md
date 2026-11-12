# 46: Une touche refusée pendant une sauvegarde dans un `textarea` ou un `input` de `main` est dite par le toast mais ne laisse aucune marque

**What to build:** La garde `beforeinput` de `src/sheafmd/page/page.js` (ticket 43, PR 259) pose `rd-saving` sur `e.target.closest('[contenteditable="true"]')`. Si la touche refusée tombe dans un `textarea` ou un `input` à l'intérieur de `main` (un formulaire de commentaire ou de réponse), `closest` rend null : le toast « Saving… » est dit, mais le champ ne porte ni trait pointillé ni curseur `not-allowed`, et rien ne reste à l'écran une fois le toast parti (2600 ms). La garde refusait déjà ces touches avant le ticket 43 ; elles sont toujours perdues, seul le toast le dit.

**Blocked by:**
- External: PR 259 (ticket 43) merged into main

**Établi (preuves) :** revue de spec de la PR 259 (`pr-43-reviews/standards.md`, section Spec (a)). Non reproduit par un test.

**Par où commencer :** dire d'abord si la garde doit refuser ces champs (une réponse de commentaire n'est pas dans la page envoyée) ; si oui, marquer le champ lui-même (`e.target`) quand il n'y a pas de bloc éditable, avec la même classe et le même retrait, et écrire un test de page : une touche dans le champ d'un formulaire ouvert pendant une sauvegarde retenue.

- [ ] Un test de page tape dans un champ de formulaire pendant une sauvegarde sans réponse et échoue tant que le champ ne porte pas de marque
- [ ] La marque part avec la sauvegarde et ne devient pas une modification

**Status:** blocked (PR 259)
