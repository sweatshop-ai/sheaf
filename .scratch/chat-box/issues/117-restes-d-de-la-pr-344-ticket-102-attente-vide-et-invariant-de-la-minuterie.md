# 117: Restes d de la PR 344 (ticket 102) : attente sans effet et invariant de la minuterie seulement en commentaire

**What to build:** Revue Opus de la PR 344 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-102-reviews/review-1.md`), classe d :
1. `tests/page/test_page_dictation.py` : le `wait_for_timeout(300)` du test « late stop after a failed send » n'attend rien (`flush()` livre l'événement dans `p.evaluate`) ; le retirer.
2. `page.js` (minuterie de 120 s) : sans la garde, la règle « chaque sortie de d efface la minuterie d'abord » ne tient que par un commentaire. Décider : un test qui la fixe, ou rien.

**Decision, point 2 (Xavier, 2026-11-14): nothing, no new test.** `test_a_recorder_that_stopped_by_itself_does_not_cut_the_next_recording_short` (test_page_dictation.py, `self_stopped_then_dictate_again`) already pins the one exit from d that does not go through `stopDictation`: the recorder's own `stop` event clears `d.timer` first, and the test fails if the first recording's 120 s timer cuts the second. The other exits (`stopDictation(true)`) clear the timer in the same function. A test per exit would repeat that one, and a future path that forgets to clear is caught by it only if it is the same path; a new path needs its own test when it is added, and the comment at page.js names the rule for whoever adds it.

**Done in PR chat-box/117, point 1:** the idle `wait_for_timeout(300)` is removed.

**Blocked by:** PR 344
**Claimed by:** Xavier

**Status:** ready-for-agent
