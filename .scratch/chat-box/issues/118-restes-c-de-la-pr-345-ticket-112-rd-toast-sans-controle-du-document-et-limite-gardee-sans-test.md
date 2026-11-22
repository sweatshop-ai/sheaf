# 118: Restes c de la PR 345 (ticket 112) : `rd-toast` dit sans contrôle du document, et la limite gardée n'a pas de test rouge

**What to build:** Revue Opus de la PR 345 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-112-reviews/opus-round1.md`, deux constats de classe c.

- `page.js` (~4461, le démarrage) : le contrôle « le keep nomme ce document » ne tourne que si `keep` est vrai. Un `rd-keep` non JSON ou faux (`null`, `0`, `""`) laisse donc `rd-toast` se dire sans contrôle du document. Comme sur main quand il n'y a pas de keep ; sans effet dans la pratique, rien n'écrit `rd-toast` sans `rd-keep` d'un autre document. Décider : contrôler aussi sans keep (rien ne nomme le document, donc le message se dit comme aujourd'hui, à écrire dans le SPEC 10.11), ou laisser tel quel.
- La limite gardée au ticket 112 (un refus rejoué encore affiché n'est pas porté par un second rechargement tardif, SPEC 10.11, l'exemple 0 s / 5 s / 8 s) n'a pas de test rouge qui la fixe : seul « refus non redit après ses 7 s » (`tests/page/test_page_actions.py`) la touche, et il ne tombe pas si la limite est levée. Écrire le test : refus dit à 0 s, rechargement à 5 s, second rechargement à 8 s, le refus n'est pas redit.

**Blocked by:** PR 345 merged

**Claimed by:** Emeka

**Status:** done (merge 65343aa, PR 352)

**Par où commencer :** `tests/page/test_page_actions.py`, à côté du test du refus qui n'est plus rejoué après ses 7 secondes ; sur le serveur auto-hébergé, jamais sur le portable.

- [x] Le contrôle du document couvre `rd-toast` sans keep, ou le SPEC dit pourquoi non
- [x] Un test rouge fixe la limite du refus rejoué (0 s, 5 s, 8 s)
