# 117: Restes d de la PR 344 (ticket 102) : attente sans effet et invariant de la minuterie seulement en commentaire

**What to build:** Revue Opus de la PR 344 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-102-reviews/review-1.md`), classe d :
1. `tests/page/test_page_dictation.py` : le `wait_for_timeout(300)` du test « late stop after a failed send » n'attend rien (`flush()` livre l'événement dans `p.evaluate`) ; le retirer.
2. `page.js` (minuterie de 120 s) : sans la garde, la règle « chaque sortie de d efface la minuterie d'abord » ne tient que par un commentaire. Décider : un test qui la fixe, ou rien.

**Blocked by:** PR 344
**Claimed by:** Xavier

**Status:** ready-for-agent
