# 137: Deux échecs de page sans cause : le send-again et « text changed while you wrote » (restes du ticket 100)

**What to build:** Le ticket 100 a établi une seule des trois causes (la course de la route, corrigée par la sonde, PR 346). Restent deux échecs de CI dont la cause n'est pas connue. Le journal du flux (« the event stream, page and hub », dans le log d'un job rouge) est en place depuis la PR 346 ; aucun log de CI avec ce journal n'a été lu sur l'un de ces deux échecs.

- `test_a_send_again_that_fails_to_reach_the_hub_does_not_hide_that_the_send_before_it_was_taken` : run 43616701956, tentative 3 (tête f76b1f5). Le toast « did not go out » est venu, donc la route était vive ; ni « New reply on c1 by Ada » ni TAKEN ensuite. Le plus fréquent (quatre PR dans une soirée, selon Rhea).
- `test_a_change_heard_between_a_replys_answer_and_its_end_reloads_when_the_send_ends_and_says_it_waited` : run 43621112432, tentative 2, job 132530249342, « timed out waiting for a toast saying 'text changed while you wrote' » ; l'étape « the hub to take the reply » était passée.
- `test_a_box_typed_in_a_block_whose_save_is_merged_is_not_ticked_before_the_reload` : run 43639875963 (PR 344), « page did not answer », puis blocage à la fermeture du contexte. Même fichier de journal manquant ; un autre test.
- Écarté : ce n'est pas la course de la route (les jobs 132567777529 et 132567777419 de la PR 328 l'étaient) ; ce n'est pas le flux dans les journaux lus : `changed` est arrivé à la page en moins de 2 ms après l'écriture du hub.

**À faire :** sur un échec réel, lire d'abord la section « the event stream, page and hub » : le hub a-t-il publié `changed`, la page l'a-t-elle reçu, un toast a-t-il été mis en file ? Établir la cause avant tout correctif, retry ou délai. Le correctif va dans la page ou le hub si c'est un défaut du produit, dans les aides de test si c'est le test.

**Blocked by:** un échec de CI avec le journal (rien à lire tant qu'il ne revient pas)

**Status:** open

- [ ] La cause de chacun des trois échecs est établie sur un échec réel avec le journal, pas supposée
- [ ] Le correctif est posé et les trois tests passent sur plusieurs lancements de CI
