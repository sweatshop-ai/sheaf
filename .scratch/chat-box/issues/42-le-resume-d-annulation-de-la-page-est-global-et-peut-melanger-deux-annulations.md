# 42: Le résumé d'annulation de la page (`cancelNote`) est global : deux annulations à moins de 60 ms se fondent en un seul toast

**What to build:** Dans `src/sheafmd/page/page.js`, `cancelSaid` collecte les événements `tell-cancelled` nommés d'un instant dans un seul objet `cancelNote`, puis dit un toast après 60 ms (PR #257, correctif du tour 3 de Codex). L'objet n'est pas lié à une annulation ni à un fil : les événements de deux annulations séparées arrivés dans les mêmes 60 ms (deux fils annulés de suite, ou un fil et une annulation de session) donnent un seul toast « Cancelled. A and B had already seen it… » qui peut mêler des agents de fils différents ; un toast en attente peut aussi remplacer celui d'une annulation de session. Classe : c (tour 4 de Codex, P2, GO sur le reste).

**Blocked by:** 257

**Établi (preuves) :** `codex-round4.md` de pr-23-reviews, constat P2. Non reproduit par un test. À noter : ce que le ticket 23 laissait de préexistant (un instantané tardif qui ressuscite un Tell terminé ; la réponse HTTP d'une annulation qui double les événements et supprime l'avertissement) est corrigé dans la PR #257 même (`endedAt`, `cancelled[id]`).

**Par où commencer :** ranger la note par fil (`cancelNote[id]`) et dire un toast par fil ; écrire un test de page : deux fils annulés de suite, un toast chacun.

- [ ] Un test de page pose deux annulations dans les 60 ms et échoue sans le correctif
- [ ] Le toast d'un fil ne nomme que les agents de ce fil
