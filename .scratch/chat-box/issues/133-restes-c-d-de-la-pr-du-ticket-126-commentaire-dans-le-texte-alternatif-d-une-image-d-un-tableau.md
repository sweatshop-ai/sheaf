# 133: Restes c et d de la PR du ticket 126: un commentaire dans le texte alternatif d'une image d'un tableau du document

**What to build:** Reste de la revue du ticket 126 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-126-reviews/opus-1.md`). Mesuré contre pandoc 3.9 :
- `| ![xx<!-- sheaf-comment id=c1 … -->](u) | yy |` (tableau hors citation ou liste) : pandoc abandonne le commentaire (il n'est pas dans le HTML) mais `parse` le trouve. Dans une citation ou une liste, `parse` et pandoc sont d'accord (rien). L'écart est donc sur un tableau du document, hérité de main ; le reste R2-2 du ticket 126 était écrit à l'envers.
- Piste : lire par pandoc aussi les blocs `table` qui contiennent un commentaire et une image (même mécanisme que `_read_tables`), ou écarter avec la preuve si c'est sans effet pour la page.
- Écarté au ticket 126 avec preuve (non reproduit, environ 100 formes, dont un document CRLF, une réponse déjà présente, `edit_body`) : une réponse dont le corps contient `\r\n` donne 0 réponse ; test d'épinglage `test_a_reply_with_crlf_in_its_body_is_read_back`.

À mesurer contre pandoc 3.9, test rouge d'abord ; chaque reste est corrigé ou écarté avec la preuve.

**Blocked by:** PR du ticket 126 fusionnée

**Claimed by:** Dries 2026-11-15 00:12

**Status:** done (sur chat-box/126, 02ec620 : un tableau du document qui porte une image et un commentaire est lu par pandoc, test rouge d'abord ; l'écart n'existe plus)

**Limites connues (revue du ticket 126, d, non corrigées) :**
- Le cache de `_read_tables` (16384 entrées) est borné par le nombre d'entrées, pas par la mémoire : dans un hub qui tourne longtemps il peut tenir quelques dizaines de Mo avant d'évincer.
- `write_outcome` du fuzzer ne vérifie que la présence du commentaire, pas que le rendu reste le même avant et après l'écriture ; une écriture qui détruit un tableau passe pour « ok ».
- (c, revue ronde 3, pré-existant) Si l'en-tête a un autre nombre de cellules que la ligne de délimitation, pandoc lit tout le bloc comme un paragraphe ; un accent grave peut y ouvrir un code qui se ferme sur la ligne paresseuse suivante, que le découpeur coupe en bloc séparé : lu seul, le bloc n'a pas de fermeture et `parse` trouve un commentaire que pandoc cache dans le code. Rare, faux sur main aussi.
- (c, revue ronde 3) Un commentaire que pandoc abandonne d'une cellule au-delà des colonnes n'est pas compté par `next_id_in` : `add_comment` peut écrire un second `id=c1` ; si le tableau gagne ensuite une colonne, le fichier a deux `c1`. Piste : faire compter à `next_id_in` tout `id=cN` brut.
- (c, revue ronde 2) Une image par référence (`![x C][r]`, `[r]:` défini ailleurs) : le commentaire est trouvé, pandoc l'abandonne, car `_read_tables` lit le bloc seul. Les citations et les listes ont la même limite.
- (cas du fuzzer, graine z1, générateur nested, faux sur la tête 3c71397 et sur le parent 4fe13e2, non analysé) Document aux fins de ligne CRLF : `'> *    q\r\n>\r\n10. r\r\n>      | h0 | h1 |\r\n>      \t|---|:-:|\r\n>      \t| w` | `z | |\r\n>      | v\\| | `z | |\r\n>      | w` | x |\r\n\r\n>      | h0 | h1 | h2 | h3 |\r\n>      |---|---|---|---|---|\r\n\r\n>      | `x | `<!-- sheaf-comment id=c1 by="A" at=2026-01-01T00:00 status=open quote="b" why -->` | y` |\r\n>      | v\\| | `y` | x | w` |\r\n> - next\r\n'`. Pandoc 3.9 (`-f gfm -t html`) lit les lignes de `>      | …` comme du code indenté dans trois citations (`<pre><code>`), donc le commentaire est dans du code et n'est pas montré ; `parse` le trouve.
