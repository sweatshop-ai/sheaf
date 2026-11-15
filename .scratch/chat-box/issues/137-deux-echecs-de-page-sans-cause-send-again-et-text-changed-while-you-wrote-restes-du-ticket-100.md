# 137: Deux échecs de page sans cause : le send-again et « text changed while you wrote » (restes du ticket 100)

**What to build:** Le ticket 100 a établi une seule des trois causes (la course de la route, corrigée par la sonde, PR 346). Restent deux échecs de CI dont la cause n'est pas connue. Le journal du flux (« the event stream, page and hub », dans le log d'un job rouge) est en place depuis la PR 346 ; aucun log de CI avec ce journal n'a été lu sur l'un de ces deux échecs.

- `test_a_send_again_that_fails_to_reach_the_hub_does_not_hide_that_the_send_before_it_was_taken` : run 43616701956, tentative 3 (tête f76b1f5). Le toast « did not go out » est venu, donc la route était vive ; ni « New reply on c1 by Ada » ni TAKEN ensuite. Le plus fréquent (quatre PR dans une soirée, selon Rhea).
- `test_a_change_heard_between_a_replys_answer_and_its_end_reloads_when_the_send_ends_and_says_it_waited` : run 43621112432, tentative 2, job 132530249342, « timed out waiting for a toast saying 'text changed while you wrote' » ; l'étape « the hub to take the reply » était passée.
- `test_a_box_typed_in_a_block_whose_save_is_merged_is_not_ticked_before_the_reload` : run 43639875963 (PR 344), « page did not answer », puis blocage à la fermeture du contexte. Même fichier de journal manquant ; un autre test.
- Écarté : ce n'est pas la course de la route (les jobs 132567777529 et 132567777419 de la PR 328 l'étaient) ; ce n'est pas le flux dans les journaux lus : `changed` est arrivé à la page en moins de 2 ms après l'écriture du hub.

**À faire :** sur un échec réel, lire d'abord la section « the event stream, page and hub » : le hub a-t-il publié `changed`, la page l'a-t-elle reçu, un toast a-t-il été mis en file ? Établir la cause avant tout correctif, retry ou délai. Le correctif va dans la page ou le hub si c'est un défaut du produit, dans les aides de test si c'est le test.

**Blocked by:** none

**Journal lu (Yara, 2026-11-15) : le send-again est revenu avec le journal.** Run 43709623494, tentative 1, job 132798137212, tête c6faee7 (PR 365, qui ne touche pas ce test) : `test_a_send_again_that_fails_to_reach_the_hub_does_not_hide_that_the_send_before_it_was_taken`, `test_page_writing.py:2885`, « timed out waiting for a toast saying 'What you sent reached the hub after all'; the toasts that went by: ['Your reply did not go out: the hub is unreachable.'] ». Vert à la tentative 2. Section « the event stream, page and hub » du log, heures UTC :
- 11:43:57.668 le hub reçoit `/_/comment` `op reply` rid fdd5…462f (le premier envoi, tenu par `slow_hub`) ; 57.679-.694 la route du test est posée et appelée (le send-again).
- 11:43:59.076-.077 le hub publie `changed` (rid fdd5…462f, `telling: []`) « to 1 stream(s) » et l'écrit ; `/_/comment out` à .077.
- 11:43:59.189 `page0 new /_/live` : la page ouvre un NOUVEAU flux 112 ms après l'écriture de `changed` ; `page0 fetch /_/doc` à .189 et .235 ; `page0 event hello` à .235.
- Aucune ligne `page0 event changed` n'apparaît dans le journal : la page n'a pas lu le `changed` du hub sur l'ancien flux, et la fin du journal est .237 alors que le test échoue 8 s plus tard. Le log porte aussi un `BrokenPipeError` du hub (`server.py:139`, `wfile.write`), juste avant le journal.
Établi : le hub a publié `changed` pour ce rid, la page n'en a pas journalisé la réception, et elle a rouvert un flux `/_/live` juste après. Non établi : pourquoi l'ancien flux n'a pas livré (flux déjà fermé côté page ? `changed` écrit sur une socket morte, cf. le BrokenPipe ?) ni si la réouverture vient d'un rechargement ou de la reprise du flux. Prochaine lecture : le code de la page qui ouvre `/_/live` (reprise après coupure) et ce que le hub compte comme « 1 stream » à cet instant ; la cause reste à établir avant tout correctif.

**Claimed by:** Yara 2026-11-15 13:29

**Status:** in-progress

- [ ] La cause de chacun des trois échecs est établie sur un échec réel avec le journal, pas supposée
- [ ] Le correctif est posé et les trois tests passent sur plusieurs lancements de CI
