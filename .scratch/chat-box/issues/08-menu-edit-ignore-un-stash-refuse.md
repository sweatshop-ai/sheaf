# 08: Menu ⋯ Edit : une réponse tapée est perdue quand le stockage refuse

**What to build:** Quand le stockage local est plein ou bloqué, ⋯ → Edit ne doit pas perdre le texte tapé dans le champ de réponse. Issu de la review du bug hunt de la PR #238 (P2 n° 2) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Claimed by:** Birgit 2026-11-11 00:18

**Status:** done (PR à ouvrir)

**Ce qui ne va pas :** `page.js:2194`. ⋯ → Edit appelle `stash()` sans lire son retour. Si `stash()` renvoie faux (stockage plein ou bloqué), l'ouverture du formulaire d'édition continue et la réponse tapée est abandonnée.

- [x] Avec un stockage qui refuse, ⋯ → Edit garde la réponse tapée (elle reste dans le champ, ou Edit ne s'ouvre pas et le dit)
- [x] Test avec un `stash()` qui renvoie faux, rouge avant le correctif
- [x] Avec un stockage qui marche, comportement inchangé
- [ ] PR séparée, CI verte

**Preuve (2026-11-11):** `test_choosing_edit_when_the_store_cannot_keep_the_reply_leaves_the_reply_in_the_field` (tests/page/test_page_chat_box.py), rouge avant le correctif (pas de toast, le formulaire d'édition remplaçait la réponse), vert après. `textForm` lit maintenant le retour de `stash()` : le formulaire remplacé reste et le toast « could not be kept » le dit. Inchangé avec un stockage qui marche : `test_choosing_edit_while_a_reply_is_typed_keeps_the_reply` et les 10 tests de store passent. La case « PR séparée » devient « une PR pour 08, 09, 11, 07 » (consigne d'Isolde) : cochée à l'ouverture de la PR.
