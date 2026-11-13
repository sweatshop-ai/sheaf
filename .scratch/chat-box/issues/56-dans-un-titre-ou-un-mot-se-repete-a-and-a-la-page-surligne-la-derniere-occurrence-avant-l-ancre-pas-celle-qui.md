# 56: Dans un titre où un mot se répète (`## A and A`), la page surligne la dernière occurrence avant l'ancre, pas celle qui a été choisie

**What to build:** Depuis le ticket 55 le bloc d'un commentaire sur des mots d'un titre est au bout du titre, quels que soient les mots choisis. La `quote` enregistre les mots, pas lesquels. Quand le titre répète le mot (`## A and A`, commentaire sur le premier `A`), la page (`src/sheafmd/page/page.js` `rangeFor`, `flat.lastIndexOf(q)`) surligne la dernière occurrence avant l'ancre, donc le second `A`; `edit.py` `_occurrence` (utilisé par `_insert_comment`) compte de la même façon. Classe : c (titre à mot répété, sélection d'une occurrence qui n'est pas la dernière).

**Blocked by:** none


**Claimed by:** Viggo 2026-11-14 00:51

**Status:** in-progress

**Par où commencer :** décider si la `quote` doit porter la position (champ ou décalage dans le bloc) ou si le surlignage de la dernière occurrence est acceptable et se documente dans SPEC 10.4. Test d'abord : `## A and A`, sélection du premier `A`, le surlignage est sur le premier.

- [ ] Décision écrite (position enregistrée, ou limite documentée dans SPEC 10.4)
- [ ] `## A and A` avec le premier `A` choisi : la page surligne le premier — preuve : test de `page.js` (sur t-compute, pas sur le portable) et test de `edit.py` pour `_occurrence`
- [ ] Un commentaire déjà écrit (sans position) se surligne comme avant
