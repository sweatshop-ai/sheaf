# 55: Un commentaire sur des mots d'un titre écrit son bloc au milieu du titre, et les autres lecteurs du fichier ne retrouvent plus le titre

**What to build:** `comments.add_comment` place le bloc juste après la fin de la sélection (`anchor_point`). Pour un titre, une sélection qui ne finit pas la ligne coupe le titre : `## Done<!-- sheaf-comment … quote="Done" --> when`. `boss-goal` (claude-boss) et AgentView lisent alors un titre qui n'est plus « Done when » et perdent toutes les cases. Constaté le 2026-11-13 sur une page de but de piste (Tarek, boss d'AgentView ; leur dossier avec les fixtures : ticket boss-track/27, branche `boss-track-27-heading-comment` de thinkingtoo/agentview, lecture seule). Classe : b (autres lecteurs du fichier).

**Blocked by:** none

**Claimed by:** Isolde 2026-11-13 10:35

**Status:** done — PR 271 merged by Rhea, main 8f285ad

**Décision (Halima, 2026-11-13) :** pour un titre, le bloc est ancré **à la fin de la ligne du titre**, quelle que soit la sélection : le texte du titre reste entier. Le retrait des commentaires HTML dans le titre d'une feuille continue de marcher (SPEC 9.11). `quote` enregistre toujours ce qui a été sélectionné. Le SPEC qui appelle voulu un bloc dans le titre est corrigé.

**Établi (preuves) :**
- `src/sheafmd/comments.py` : `add_comment` pose le bloc à `_block_offsets[block] + anchor_point(...)` ; `ONE_LINE_KINDS = {"heading", "table"}` écrit tout le commentaire sur une ligne ; rien ne ramène l'ancre d'un titre au bout de la ligne.
- `tests/test_anchoring.py::test_insertion_point` fixe aujourd'hui l'ancre au milieu : `("## A heading here\n", "heading", "## A heading| here\n")`. Ce cas change.
- Même chemin dans `edit.py::_insert_comment` : quand la page enregistre un bloc modifié, un commentaire existant est remis après la dernière occurrence de sa `quote` : dans un titre, au milieu aussi. Le correctif y passe par la même règle.
- Titres à deux formes que la règle doit tenir : ATX avec séquence de fermeture (`## Done ##` : le bloc après les `##` en fait du texte, pandoc rend « Done ##<!-- c --> », id `done-`) et setext (`Title\n=====` : le bloc va au bout de la ligne de texte, avant le soulignement).

**Cellule de tableau (demandé) :** même défaut, plus bas : une sélection au milieu d'une cellule met le bloc dans les mots de la cellule (`| on<!-- sheaf-comment … -->e | two |`, vérifié avec pandoc gfm : la cellule est « on<!--…-->e »), donc un lecteur qui compare le texte d'une cellule le voit coupé. Le correctif du titre ne s'y applique pas tel quel : la fin de la **ligne** est après le `|` final, hors de toute cellule, et l'ancre du badge se lit par cellule. Le pendant est la fin de la **cellule** (avant son `|`, en comptant `\|` et le code en ligne) : ticket à part, non fait ici.

**Par où commencer :** une fonction de `comments.py` qui donne le point d'ancre d'un bloc selon son type (titre : fin du texte du titre, avant la séquence de fermeture ATX, avant le soulignement setext ; autre : `anchor_point`), appelée par `add_comment` et `_insert_comment`. Test d'abord.

- [x] Un commentaire sur un mot du milieu d'un titre ATX, ATX fermé et setext est écrit au bout du titre ; le texte du titre est entier, `quote` garde les mots choisis — preuve : tests unitaires de `add_comment`, rouges avant
- [x] `_insert_comment` (enregistrement d'un titre modifié) remet un commentaire existant au bout du titre — preuve : test de `edit.py`
- [x] Le SPEC ne dit plus qu'un bloc dans le titre est voulu (la phrase de 9.11 et l'ancrage de 10.4), et dit la règle du titre
- [x] Le cas des cellules est écrit dans le ticket qui suit : 57

**Revue (2026-11-13, Opus ; Codex sans jetons jusqu'au 18 nov) :** deux défauts réels corrigés dans la suite de 4824d24 : un titre qui finit par une barre oblique inverse (le bloc va avant elle) et un titre sans mots (`#`, `# `) : le bloc va sur sa propre ligne, le titre reste un titre. **Limite restante, non corrigée :** dans un titre où un mot se répète (`## A and A`), la page surligne la dernière occurrence avant l'ancre (`page.js` `rangeFor`, `edit.py` `_occurrence`), pas celle qui a été choisie ; la `quote` enregistre les mots, pas lesquels. Ticket 56. **Cellules :** ticket 57 (fin de la cellule). Revue 2 (Opus, GO, classe c seulement) : ticket 58.
