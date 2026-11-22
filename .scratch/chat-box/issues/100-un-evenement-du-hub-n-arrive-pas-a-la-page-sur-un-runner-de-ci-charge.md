# 100: Un événement du hub n'arrive pas à la page sur un runner de CI chargé

**What to build:** Trois tests de page ont échoué en CI parce qu'un événement que le hub envoie à la page n'est jamais arrivé (ou arrivé trop tard), jamais sur le serveur auto-hébergé à la main :

- `tests/page/test_page_writing.py::test_a_send_again_that_fails_to_reach_the_hub_does_not_hide_that_the_send_before_it_was_taken` : run 43616701956, tentative 3 (tête f76b1f5, avec le correctif du ticket 79). Le message dit `the toasts that went by: ['Your reply did not go out: the hub is unreachable.']` : après ce toast, ni « New reply on c1 by Ada » ni « What you sent reached the hub after all » en 8 s d'attente avec l'horloge qu'on fait avancer. Les 7 autres lancements (CI et le serveur auto-hébergé) ont passé, avec la même chronologie.
- `tests/page/test_page_writing.py::test_a_page_that_opens_a_thread_while_a_send_of_it_is_out_on_another_page_does_not_draw_its_text` : run 43621112432, tentative 1, job 132526782610, « timed out waiting for the send to go out » (`pagehelp.py:184`).
- `tests/page/test_page_writing.py::test_a_change_heard_between_a_replys_answer_and_its_end_reloads_when_the_send_ends_and_says_it_waited` : run 43621112432, tentative 2, job 132530249342, « timed out waiting for a toast saying 'text changed while you wrote' ».

**Écarté (ticket 79, PR 317) :**
- Ce n'est pas la file des toasts seule : avec l'horloge qu'on fait avancer pendant qu'un toast est à l'écran, le toast attendu n'est jamais venu dans le cas du send-again.
- Ce n'est pas la lenteur de la machine pour la chronologie : sur le serveur auto-hébergé (10 lancements, dont avec le processeur saturé par 4 boucles sur son cœur, et 64 boucles sur 32 cœurs) et sur une exécution de CI qui passe, la chronologie est la même au dixième de seconde près (« did not go out » à 7,2 s, « New reply » à 14,2 s, TAKEN à 16,8 s, soit 9,6 s après la libération du hub).
- Quatre exécutions de CI avec un vidage de l'état de la page à l'échec (branche jetable, supprimée) sont toutes passées : rien attrapé.

**Piste, non vérifiée :** l'événement `changed` du hub (flux SSE) ou la réponse de `/_/doc` n'arrive pas à la page, ou la page ne le traite pas, sur un runner où six travailleurs poussent de la CI en même temps. À établir par une mesure, pas par une hypothèse.

**Blocked by:** none


**Claimed by:** Isolde 2026-11-14 18:59

**Status:** done: merged as 3c4bc18 (PR 346), closed on Rhea's word

**PR 346 (2026-11-14) :** une des trois défaillances est établie : `page.route()` rend la main avant que Chromium n'intercepte, un envoi fait quelques ms plus tard part droit vers le hub (test_page_writing « timed out waiting for the send to go out »). Corrigé côté test (sonde) et journal du flux ajouté (une page rouge imprime « the event stream, page and hub »). Reste ouvert : le send-again (la route était vive, TAKEN ne vient pas) et « text changed while you wrote » ; il faut un échec réel avec le journal. Restes de revue : ticket 119. Handoff : /home/tiroir/.claude/pm/chat-box-handoffs/handoff-Isolde-100.md

**Par où commencer :** `src/sheafmd/page/page.js` autour de `live.addEventListener('changed', …)` (≈ ligne 4180) et `meetTaken` (≈ ligne 1701).

- [x] La page note, dans un journal lu par le test à l'échec, l'ouverture, les erreurs et chaque message du flux (heure de la page), et le hub note l'heure de chaque publication ; sur un échec de CI, on lit les deux côte à côte
- [x] ~~La cause est établie sur un échec réel (flux coupé, événement perdu côté hub, ou reçu et non traité côté page), pas supposée~~ → (struck, moved to ticket 137, which moved the rest to ticket 141) : établie pour une des trois défaillances (la course de la route, PR 346) ; le send-again et « text changed while you wrote » n'ont pas de cause, aucun log de CI avec le journal n'a été lu
- [x] ~~Le correctif est dans la page ou le hub si c'est un défaut du produit, dans les aides de test si c'est le test ; les trois tests passent sur plusieurs lancements de CI~~ → (struck, moved to ticket 137, then 141) : corrigé pour la course de la route (sonde, 0 échec sur 45 tours contre 3 sur 15) ; pas de correctif pour les deux autres sans cause

**Fermeture (Isolde, 2026-11-15) :** la case 1 est faite ; les cases 2 et 3 sont barrées vers le ticket 137. La PR 346 le dit : la course de la route (`page.route()` rend la main avant que Chromium intercepte) est établie sur des échecs réels avec le journal et corrigée par la sonde (3 échecs sur 15 tours avant, 0 sur 45 après ; la course elle-même n'a jamais été vue attrapée). Deux échecs du ticket (send-again ; « text changed while you wrote ») et le test de la PR 344 n'ont aucune cause : aucun log de CI avec le journal n'en a été lu. Le journal est en place ; si l'un revient, lire la section « the event stream, page and hub » du log (ticket 137). Le ticket 138 est à part : Chromium qui ne démarre pas sur un runner.
