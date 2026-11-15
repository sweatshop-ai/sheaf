# 143: Un refus rejoué par un rechargement poste un nouvel incident `toast` à `/_/diag` à chaque rejeu (reste du ticket 101, point 2)

**What to build:** Point 2 du ticket 101 : « chaque rejeu poste un incident `toast` à `/_/diag` ». La PR 339 (ad83e80) a borné la durée du rejeu (l'échéance d'origine est gardée, `page.js:4562`) mais pas cette moitié. Sur origin/main, le rejeu du démarrage appelle `say(refusedPress.text, true)` (`page.js:4559`) et `say` poste `incident('toast', { message })` pour toute erreur (`page.js:660`). Chaque rechargement qui rejoue le même refus dans sa fenêtre de 7 s écrit donc une ligne de plus dans le journal pour un refus déjà noté. Le SPEC 10.11 ne le dit pas. Classe d : bruit de journal, aucun effet visible.

**Blocked by:** none

**Status:** open

**Par où commencer :** décider : le rejeu ne poste pas d'incident (un paramètre de `say`, ou un rejeu sans `err` pour le journal), ou la limite est écrite dans le SPEC 10.11 (« chaque rejeu est un incident »). Test rouge d'abord, sur t-compute, jamais sur le portable : un refus dit, un rechargement dans les 7 s, une seule ligne `toast` dans `/_/diag`.

- [ ] Le rejeu d'un refus ne poste pas d'incident, ou la limite est écrite dans le SPEC 10.11
