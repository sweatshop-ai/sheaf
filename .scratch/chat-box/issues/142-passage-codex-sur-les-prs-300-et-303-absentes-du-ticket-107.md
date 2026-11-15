# 142: Passage Codex sur les PR 300 et 303 : le ticket 107 ne les liste pas

**What to build:** Le ticket 99 dit que « le passage Codex des PR 300 et 303 est passé au ticket 107 », mais le tableau et la classification du ticket 107 ne nomment ni la PR 300 ni la PR 303. Le passage n'a donc pas de ticket qui le porte (trouvé par l'audit des cases vides, 2026-11-15). À faire :
1. Classer les deux PR avec la règle par risque du ticket 107 (Codex seulement pour une PR de porte, de sécurité, de déploiement ou de données). Elles touchent `src/sheafmd/comments.py` (lecture des commentaires, PR 300, merge 1521562, tête 190bc94) et `src/sheafmd/render.py` (refus de la copie à partager, PR 303, merge ff5aaf7) ; le refus de la copie est ce qui empêche une note de relecteur de fuir, à peser.
2. Si « oui » : `/codex-review --base` sur le diff de chaque fusion contre son premier parent, rapport dans `/home/tiroir/.claude/pm/chat-box-handoffs/pr-82-codex/pr-<N>.md`, trouvailles classées a/b/c/d (a et b : correction avec test rouge d'abord ; c et d : tickets). Si « non » : écrire la raison ici et fermer.
Origine : tickets 76 (case 5), 83 (point 5), 99.

**Blocked by:** none

**Claimed by:** Birgit 2026-11-15

**Status:** done (classées ; le passage Codex de la PR 300 est une ligne du tableau du ticket 107)

- [x] Les deux PR sont classées (Codex oui ou non), la raison écrite (PR 300 : oui ; PR 303 : non ; raisons dans la classification du ticket 107)
- [x] ~~Si oui : rapports Codex enregistrés, trouvailles classées a/b/c/d, a et b corrigées avec un test rouge, c et d en tickets~~ (moved to ticket 107 : la PR 300 y est ajoutée au tableau, bloqué par la limite de Codex jusqu'au 2026-11-20 14:10)

**Classification (Birgit, 2026-11-15, règle par risque du ticket 107) :**
- **PR 300 : Codex oui.** Elle réécrit le lecteur des spans de code de `comments.py`. `_mask_code` s'appuie dessus, et `render.py` (ligne 610 sur main) l'appelle pour savoir quel texte est du code, donc ce qu'un ouvreur non fermé n'est pas, dans le contrôle de la copie à partager qui refuse de livrer une note de relecteur. Une mauvaise lecture d'un span peut laisser passer ce que le contrôle devrait refuser : une porte. Les deux revues Opus ont comparé 9 330 chaînes à pandoc, mais un autre modèle est le but.
- **PR 303 : Codex non.** Elle change le message d'un refus qui existait déjà (`UnclosedComment(empty=...)`), la regex de bordure de cellule et la lecture des empans de commentaires pour la suppression ; le refus lui-même ne change pas, et le lecteur de spans qui alimente la porte est celui de la PR 300. Une revue Opus (`pr-76-reviews/opus-1.md`) a trouvé un b, corrigé dans la PR.
