# 87: Point 2 du ticket 75 et restes de la PR 307 : lire un tableau cellule par cellule dans une citation ou une liste, à partir du sourcepos de pandoc

**What to build:** Reste (c, comme main) de la ronde 2 de la PR 307 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-75-reviews/round2-narrow.md`. `_table_row_lines` (`src/sheafmd/comments.py`) ne voit pas de tableau quand la ligne d'en-tête ressemble elle-même à un rang de délimitation, alors que pandoc en lit un. Dans ce cas `parse` lit le bloc d'une citation ou d'une liste d'un seul tenant : un code qui court d'une cellule à l'autre y est du code, et un commentaire peut être perdu ou mal placé (même comportement que main, rien de perdu qui ne l'était déjà). Entrées vues avec le fuzzer (cellules vues par `pandoc -f gfm+sourcepos`, les lignes sont comptées depuis 0) :
- `> |---|\n> |---|\n> | `p | q` | r |\n` : pandoc lit les lignes 0 et 2 comme cellules.
- `> - |---|\n>   |---|\n>   | `p | q` | r |\n`
- `1. |---|---|\n   |---|---|\n   para text\n   |---|\n` : lit la ligne 0.
- `> - ---|---\n>   ---|---\n>   | x | y |\n` : lignes 0 et 2.
À faire : un test rouge par forme, comparé à pandoc (voir `_pandoc_cell_lines` dans `tests/test_anchoring.py`), puis que `_table_row_lines` reconnaisse l'en-tête qui ressemble à un délimiteur quand pandoc en fait un tableau ; ou garder la limite et la noter dans le SPEC 10.4 avec la raison. Relancer le fuzzer contre pandoc (blocs de 2 à 7 lignes de fragments, préfixes `> `, `- `, `> > `, `1. `, `> - `) : zéro ligne vue comme rang que pandoc ne voit pas, et les faux négatifs restants nommés.

**Ajouts de la ronde 3** (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-75-reviews/round3-narrow.md`, tous de classe c : main perd le même commentaire). Le c1 (indentation d'une ligne de continuation sous un item) est corrigé dans la PR 307 ; restent :
5. (c2) Une tabulation après un marqueur de liste ne compte pas la bonne largeur dans une citation : `> -\t| a ` | b C1 ` |\n>   |---|---|\n` (tester aussi `> - | a ` | b C1 ` |\n>    |---|---|\n`).
6. (c3) Un tableau qui ouvre un item suivant, juste sous l'item d'avant, n'est pas vu : `- q\n- | a ` | b C1 ` |\n  |---|---|\n` et `1. q\n2. | a ...`.
7. (c4) Pandoc continue un tableau à travers des lignes qui ouvrent un conteneur dans l'item, le code s'arrête : `- | x | y |\n  ---|---\n  - item | z\n` et `> | a |\n> |---|\n> > | a | b |\n`.

**Ajouts de la ronde 4** (`round4-narrow.md`) : la PR 307 ne lit plus un tableau cellule par cellule que dans une citation simple (`> ` avec son espace, sans item de liste dedans) ou un item de liste simple (un marqueur par ligne, ni citation ni tabulation avant le texte) ; toute autre forme est lue d'un bloc comme sur main (SPEC 10.4, limite 1). Ce que ce choix abandonne, et que ce ticket peut reprendre, avec le test « jamais pire que main » (compteur « head wrong where main right » à 0/0 sur le fuzzer `fuzz2.py`/`fuzz3.py`, dans le scratchpad de la session Isolde) :
8. (a, ronde 4) Une citation ouverte après un marqueur de liste : `1. > | a | b |\n  > |---|---|\n  > | `x | `C1` | y` |\n` (le `>` à gauche de la colonne de contenu de l'item ferme l'item) ; aussi `-  > ...` et `+\t> ...`, `- > | a | b |`.
9. (b, ronde 4) Une tabulation après `>` : `> |a|b|\n>\t  |---|---|\n> | `x | `C1` | y` |\n` (une seule colonne de la tabulation est l'espace facultatif de la citation, le reste est de l'indentation).
10. (b, ronde 4) `>` sans son espace : `>- | a | b |\n>  |---|---|\n>  | `x | `C1` | y` |\n`, `>10. | a | b |`.
11. (b1, ronde 3) Un item dans une citation, une rangée revenue à la colonne de la citation ferme le tableau : `> - q\n>\n>   | a | b |\n>   |---|---|\n> | `x | `C1` | y` |\n`.
Une façon de les reprendre : mesurer les colonnes à l'intérieur de la citation (`>` plus une colonne facultative, le reste d'une tabulation est de l'indentation), exiger qu'une citation ouverte dans un item soit à la colonne de contenu de l'item ou au-delà, et élargir `_plain` forme par forme, chacune avec le fuzzer.

**La leçon des rondes 1 à 5 de la PR 307 (à lire d'abord).** Le point 2 du ticket 75 (masquer le code cellule par cellule sur les rangs d'un tableau dans une citation ou une liste) a été retiré de la PR 307 après cinq rondes (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-75-reviews/` : `opus-1.md`, `round2-narrow.md`, `round3-narrow.md`, `round4-narrow.md`, `round5-narrow.md`, et `round6-final.md`). Chaque ronde a trouvé le bord suivant d'une relecture à la main des marqueurs de conteneur (`_bare`, `_table_row_lines`, `_plain`, que le commit `9e5d6ad` de la branche `chat-box/75` garde dans son historique) : un titre au-dessus du tableau, une citation dans un item, un item dans une citation, une tabulation ou `>` sans espace, plusieurs tableaux dans un bloc, un paragraphe de liste sur des lignes `|`. **Ne pas relire les marqueurs à la main. Demander à pandoc** : le sourcepos (`pandoc -f gfm+sourcepos -t html`) donne, pour chaque cellule `<th>`/`<td>`, la ligne et la colonne source ; un rang du tableau est une ligne qui porte une cellule, et les plages de code sont celles que pandoc rend en `<code>`. Mesure d'acceptation : le fuzzer end-to-end (`pandoc` rend le commentaire en HTML brut ou en `<code>` ; `parse` doit dire la même chose), compteurs « head wrong where main right » à 0 perdu / 0 fantôme sur tous les générateurs (`fuzz2.py`, `fuzz3.py`, `fuzz4.py` dans le scratchpad de la session Isolde de la PR 307, à recopier dans `tests/`), y compris les écritures (`add_comment`, `reply`), pas seulement `parse`.

**Blocked by:** none

**Claimed by:**

- [ ] Les formes des points 1 à 11 traitées ou la limite gardée avec la raison
- [ ] Le point 2 du ticket 75 refait à partir du sourcepos, SPEC 10.4 limite (1) retirée
- [ ] CI verte

**Status:** ready-for-agent
