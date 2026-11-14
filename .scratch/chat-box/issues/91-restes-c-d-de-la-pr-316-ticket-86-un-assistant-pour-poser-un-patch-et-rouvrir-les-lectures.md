# 91: Restes c/d de la PR 316 (ticket 86) : un assistant qui pose un patch de la page et rouvre les lectures en un seul appel, et détails de test

**What to build:** Restes de la revue Opus de la PR 316 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-86-reviews/review-1.md`), aucun de classe a ou b.

- **(c)** `tests/page/test_page_chat_box.py` :904-905 et :925-926 : une lecture de la page entre `store_unreadable(p, False)` et `hold_time_passes` purge la réponse prise avant que l'horloge saute. Le test reste vert mais ne montre pas quelle lecture a retiré l'entrée.
- **(c)** :989 et :1020 : un assistant qui pose un patch de la page et rouvre les lectures dans un seul `evaluate` supprimerait cette classe de défaut (l'ordre des deux appels, cause du ticket 86). Il ferme aussi le « d » de `handoff-Imani-2026-11-14.md`:19.
- **(d)** :1020 : le commentaire pourrait dire « un stockage qui fonctionne » en toutes lettres.
- **(d)** :1000 : le nom dit « par les lectures seulement », mais le test ne distingue pas si le premier refus d'écriture vient d'une lecture ou d'un redessin (antérieur à la PR).
- **(d)** :444-452 : `store_full` ne refuse pas `removeItem` ; le test repose sur l'entrée « pears » (déjà commenté à :1003).

**Blocked by:** PR 316

**Claimed by:**

**Status:** ready-for-agent
