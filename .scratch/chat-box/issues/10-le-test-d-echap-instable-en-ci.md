# 10: Le test d'Échap échoue de temps en temps en CI : trouver la cause

**What to build:** Le test d'Échap (keep / drawKept / closePopover) échoue parfois en CI alors qu'il passe sur un portable. La cause n'est pas établie. Issu de la review du bug hunt de la PR #238 (P2 n° 4) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Status:** ready-for-agent

**Ce qui ne va pas :** le test d'Échap. Ses assertions sont saines et la review n'a trouvé aucun bug de produit qui perde des données : Échap seul ne peut ni quitter la boîte ni la redessiner. Le commit `54abdda` n'a ajouté que des diagnostics : à l'échec, le test imprime ce que la page contenait (la boîte et ses formulaires, quand `#rd-popover` a été retiré ou ajouté, le stockage). Un `POPOVER_STATE` sans clé `log` veut dire que la page s'est rechargée. À lire à la prochaine occurrence, avant toute hypothèse.

- [ ] Au prochain échec en CI, la sortie de `54abdda` est lue et la cause écrite dans ce ticket avec la preuve
- [ ] Le correctif traite cette cause, pas un délai ou une relance
- [ ] Si la cause est un défaut du test, il est corrigé ; si c'est un défaut du produit, un ticket à part est ouvert
- [ ] Les diagnostics de `54abdda` sont retirés ou gardés, avec la raison
- [ ] CI verte sur trois passages de suite
