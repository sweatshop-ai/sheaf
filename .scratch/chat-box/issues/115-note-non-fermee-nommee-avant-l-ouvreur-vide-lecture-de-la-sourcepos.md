# 115: Une note non fermée est nommée avant l'ouvreur vide `<!-->` sur la même ligne (point 3 du ticket 83, refait, à reprendre)

**What to build:** Sur une ligne qui porte `<!-->` et une tête de note de relecteur (`<!-- sheaf-comment`) que rien ne ferme, le refus d'un export nomme la note (le message de la note est plus utile ; main donne celui de l'ouvreur vide ; rien ne fuit dans les deux cas). Une tête fermée par la ligne, ou que pandoc montre comme code, n'est pas la faute.

**Tentative du ticket 99 (PR 342, non fusionnée dans cette forme, code retiré) :** reconnaître le code par la sortie de pandoc `-f gfm+sourcepos` : un `<code>` ou `<pre>` avec `data-pos="l1:c1-l2:c2"` couvre-t-il (ligne, colonne) de la tête ? Colonne = `len(texte_avant.expandtabs(4)) + 1` (pandoc compte une tabulation jusqu'au multiple de 4 suivant et une lettre décomposée comme deux colonnes). Les tests de la PR 325 (fermée, code, tab, NFD) passaient. La revue Opus (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-99-reviews/opus-1.md`) a trouvé trois a, donc arrêt :
1. Un span de code qui traverse une ligne dans une citation ou un item de liste a un `data-pos` à deux plages : `"1:13-1:32;2:3-2:5"`. Il faut lire chaque plage séparée par `;`. `"> A <!--> b \`<!-- sheaf-comment\n> x\` c\n\nSECRET\n"` donnait la note (main : l'ouvreur vide).
2. Dans une liste, pandoc met sur `<pre>` la position de la liste ou de l'item, pas celle du bloc : `<pre data-pos="1:1-9:1">`. Un bloc de code dans un item fait compter toutes les lignes suivantes de l'item comme du code. `"- a\n\n  \`\`\`\n  z\n  \`\`\`\n\n  <!--> <!-- sheaf-comment x\n\nSECRET\n"` donnait l'ouvreur vide, la note était attendue. Ne pas se fier aux `<pre>` dans les listes (lire le contenu du `<pre>`, ou ne se fier qu'au `<code>` en ligne et aux blocs hors liste ?).
3. Performance : lancer la sourcepos à chaque refus coûte 20 s de plus sur un document de 378 Ko (sortie 7,9 Mo contre 615 Ko). Ne la lancer que si la ligne a une tête candidate.
Autres (c) : échec ou délai de pandoc dans la lecture de la sourcepos nomme la note (côté sûr) ; une tête dans l'attribut d'un html brut (`<span title="<!-- sheaf-comment">`) serait nommée note.

**Leçon :** la position de pandoc est fiable pour l'inline hors conteneur ; dans les conteneurs elle a des plages multiples et des blocs qui portent la position du parent. Prévoir les tests de ces formes (citation, liste, item avec bloc de code, span sur deux lignes) avant le code.

**Pas dans ce ticket (même chose que main, côté sûr) :** `[l](http://x/<!-->) -->` est copié avec le lien détruit (la page montre `[l](http://x/` en texte). SPEC 6.2 ne le couvre pas ; décider s'il faut le refuser.

**Blocked by:** 116, 87, 118 (leurs PR touchent SPEC.md)

**Décision (Rhea, 2026-11-14) :** pas de troisième tentative ; fermer avec une limite dans la SPEC une fois ces PR fusionnées (seul le message du refus change, rien ne fuit).

**Claimed by:**

**Status:** ready-for-agent
