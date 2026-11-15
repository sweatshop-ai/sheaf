# 123: Restes d de la PR 350 (tickets 117, 108) : la même attente vide dans le test jumeau

**What to build:** Revue Opus de la PR 350 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-117-reviews/review-1.md`), classe d, aucune de classe a, b ou c :
1. `tests/page/test_page_dictation.py` (autour de :428) : `test_the_stop_event_that_comes_late_leaves_the_new_recording_alone` garde le même `wait_for_timeout(300)` après le même `flush()` synchrone ; le retirer comme dans la PR 350. Les autres `wait_for_timeout(300)` du fichier sont à regarder un par un : seuls ceux qui suivent un `flush()` ou un événement synchrone n'attendent rien.
2. Sans cette attente, `assert hub.posts == []` ne contrôle qu'un instant ; sans gravité (l'assert `aria-pressed` attraperait la régression), rien à faire.
3. Le `clearTimeout` de `stopDictation` n'a pas de test propre : filet de sécurité, décision de la PR 350 maintenue (pas de test).

**Blocked by:** PR 350

**Claimed by:** Mira

**Status:** done (PR 354, merge 2a87788)

## Decision (Mira, PR chat-box/122)

1. The twin wait after `flush()` in `test_the_stop_event_that_comes_late_leaves_the_new_recording_alone` is out. So is the one in `test_the_stop_event_that_comes_late_leaves_the_idle_button_of_a_form_that_came_back_...`: also after `flush()` and a `stops === 1` wait, and it asserts only synchronous results (aria-pressed, recorder state).
2. The other eleven `wait_for_timeout(300)` stay (the file has three more 20 ms polling waits inside `until`; they guard nothing and are not part of this). In the fake microphone `stop()` dispatches its events synchronously unless `lateStop` holds them for `flush()`; each wait that is left guards a negative assertion on something that comes after: a POST that must not go out (`hub.posts == []`, lines 178, 193, 220, 305), a late promise or route answer (258, 387, 406), a timer run on the clock (527, 542), or a page that must not render a button (117, 125).
3. Items 2 and 3 of the ticket: nothing to do.


Close-out: item 1 done (PR 354); items 2 and 3 of the ticket ask for nothing (struck, no change).
