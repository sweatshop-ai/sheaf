# 07: Page montée : un toucher dans la zone vide de la boîte met le curseur dans le champ

**What to build:** Sur la page montée (shadow DOM), un toucher dans la zone vide de la boîte ne met pas le curseur dans le champ, alors que la spec le prévoit en repli. Issu de la review du bug hunt de la PR #238 (P2 n° 1) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Status:** ready-for-agent

**Ce qui ne va pas :** `page.js:2652-2656`. L'écouteur `touchend` est posé sur `document` ; sur la page montée il voit l'hôte du shadow DOM comme cible, donc `box.contains(e.target)` est faux et le champ n'est jamais focalisé. `tests/page/test_mount_touch.py` ne couvre que `letGoOfPageWords`, pas ce repli.

- [ ] Sur la page montée, un toucher dans la zone vide de la boîte met le curseur dans le champ (test dans `tests/page/test_mount_touch.py`, rouge avant le correctif)
- [ ] Même comportement sur la page autonome, inchangé
- [ ] Un toucher hors de la boîte ne focalise rien
- [ ] PR séparée, CI verte
