# 30: un brouillon que l'utilisateur a vidé pendant une lecture refusée revient quand la lecture réussit

**What to build:** Quand le champ d'un nouveau message est vidé et que l'effacement du brouillon gardé n'a pas pu se faire (lecture refusée), retenir l'effacement à faire et l'appliquer à la prochaine lecture réussie.

**Blocked by:**
- External: PR 250 (tickets 21 et 29) merged into main

**Claimed by:** 

**Status:** ready-for-agent

**Ce qui ne va pas :** `page.js` ~2883-2884 : depuis le ticket 29 le champ vidé ferme la boîte même si `draftsReplace(own)` n'a pas écrit ; l'entrée gardée reste, et revient dans le champ (et dans la ligne « not sent ») quand le stockage relit. Périmé, pas perdu ; plus sûr que la boîte tenue ouverte. Issu de la revue Opus du tour 2 de PR 250 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-21-reviews/codex-round2.md`), P2 mise de côté.

- [ ] lecture refusée, champ vidé, boîte fermée, lecture rétablie : le brouillon vidé ne revient pas, test rouge avant le correctif
