# 142: Passage Codex sur les PR 300 et 303 : le ticket 107 ne les liste pas

**What to build:** Le ticket 99 dit que « le passage Codex des PR 300 et 303 est passé au ticket 107 », mais le tableau et la classification du ticket 107 ne nomment ni la PR 300 ni la PR 303. Le passage n'a donc pas de ticket qui le porte (trouvé par l'audit des cases vides, 2026-11-15). À faire :
1. Classer les deux PR avec la règle par risque du ticket 107 (Codex seulement pour une PR de porte, de sécurité, de déploiement ou de données). Elles touchent `src/sheafmd/comments.py` (lecture des commentaires, PR 300, merge 1521562, tête 190bc94) et `src/sheafmd/render.py` (refus de la copie à partager, PR 303, merge ff5aaf7) ; le refus de la copie est ce qui empêche une note de relecteur de fuir, à peser.
2. Si « oui » : `/codex-review --base` sur le diff de chaque fusion contre son premier parent, rapport dans `/home/tiroir/.claude/pm/chat-box-handoffs/pr-82-codex/pr-<N>.md`, trouvailles classées a/b/c/d (a et b : correction avec test rouge d'abord ; c et d : tickets). Si « non » : écrire la raison ici et fermer.
Origine : tickets 76 (case 5), 83 (point 5), 99.

**Blocked by:** Codex usage limit until 2026-11-20 14:10 (si la classification dit « oui »)

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] Les deux PR sont classées (Codex oui ou non), la raison écrite
- [ ] Si oui : rapports Codex enregistrés, trouvailles classées a/b/c/d, a et b corrigées avec un test rouge, c et d en tickets
