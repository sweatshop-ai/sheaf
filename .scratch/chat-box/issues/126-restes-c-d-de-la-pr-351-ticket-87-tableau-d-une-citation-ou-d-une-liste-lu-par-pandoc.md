# 126: Restes c et d de la PR 351 (ticket 87): un tableau dans une citation ou une liste, lu par pandoc

**What to build:** Restes de la revue Opus de la PR 351, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-87-reviews/opus-1.md` (rondes 1 et 2). Aucun n'est de classe a ou b après les corrections de la PR.
- Limite connue (SPEC 10.4, mesurée par `tests/fuzz_containers.py`, moins d'un cas sur dix contre un sur cinq sur main) : le découpeur coupe une citation ou une liste à une ligne qui ressemble à une ligne de délimitation (`- |:-:|---|`, une rangée à une autre indentation que le tableau) là où pandoc ne lit pas de tableau ; la partie qui porte le commentaire n'a alors pas de ligne de délimitation et reste lue comme sur main (code sur tout le bloc). Piste : faire lire à pandoc le texte du document entier, pas le bloc du découpeur, ou corriger le découpeur.
- R2-1 (d) : le repli par la première ligne (`_head_of`) garde la copie d'une cellule abandonnée quand un commentaire de même id, bloc HTML à lui seul, la suit dans le même bloc : `parse` signale « duplicate id » sur la mauvaise ligne.
- R2-2 (d) : un commentaire dans le texte alternatif d'une image d'un tableau cité (`> | ![xx<!--…-->](u) | yy |`) n'est pas vu ; pandoc l'abandonne. Un tableau hors conteneur le voit.
- F5 (d) : le cache de `_read_tables` (1024 entrées) ne garde rien au-delà ; un document de plus de 1024 blocs citation/liste avec tableau et commentaire relance pandoc à chaque `parse`.
- Hors PR, vrai sur main : une réponse dont le corps contient `\r\n` donne 0 réponse.

À mesurer contre pandoc 3.9, test rouge d'abord ; chaque reste est corrigé ou écarté avec la preuve.

**Blocked by:** none


**Claimed by:** Rashid 2026-11-14 23:49

**Status:** in-progress
