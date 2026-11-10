# 11: fillPopover ramène le curseur dans le premier formulaire

**What to build:** Quand plusieurs formulaires sont ouverts, le curseur ne doit pas sauter vers le premier. Issu de la review du bug hunt de la PR #238 (P2 n° 5) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Status:** ready-for-agent

**Ce qui ne va pas :** `page.js:2052-2053`. `fillPopover` refocalise `forms[0]` dès qu'un formulaire avait le focus. Avec deux formulaires ouverts, le curseur peut sauter du second au premier pendant qu'on tape.

- [ ] Avec deux formulaires ouverts, le focus reste dans celui où l'on tape après un appel à `fillPopover`
- [ ] Test à deux formulaires, rouge avant le correctif
- [ ] Avec un seul formulaire, comportement inchangé
- [ ] PR séparée, CI verte
