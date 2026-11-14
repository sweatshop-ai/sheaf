# 87: Restes de la PR 307 (ticket 75) : un tableau dont l'en-tête ressemble à un délimiteur, dans une citation ou une liste, est lu d'un bloc

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

**Blocked by:** PR 307 mergée

**Claimed by:**

- [ ] Les formes des points 1 à 7 traitées ou la limite gardée avec la raison
- [ ] CI verte

**Status:** ready-for-agent
