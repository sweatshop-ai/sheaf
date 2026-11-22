# 141: Deux échecs de page dont la cause n'est pas montrée : « text changed while you wrote » et la case d'un bloc fusionné (restes du ticket 137)

**What to build:** Le ticket 137 a établi la cause du send-again (PR 373 : une vérification `/_/doc` rechargeait avant le `changed` en attente). Deux échecs de CI restent sans cause prouvée :

- `test_a_change_heard_between_a_replys_answer_and_its_end_reloads_when_the_send_ends_and_says_it_waited` : run 43621112432, tentative 2, job 132530249342, « timed out waiting for a toast saying 'text changed while you wrote' » ; l'étape « the hub to take the reply » était passée.
- `test_a_box_typed_in_a_block_whose_save_is_merged_is_not_ticked_before_the_reload` : run 43639875963 (PR 344), « page did not answer », puis blocage à la fermeture du contexte.

Rien ne prouve que ce soit la cause du 137 ; elle est la première piste (une vérification qui recharge avant un événement en attente et emporte un toast), car le journal de ces deux échecs a été lu sans savoir qu'un rechargement l'efface.

**À faire :** (1) sur un échec rouge, lire le journal « the event stream, page and hub », qui survit maintenant à un rechargement (`document starts`, `pagehide`) ; (2) établir la cause avant tout correctif, retry ou délai ; (3) correctif test-first dans la page ou le hub si c'est un défaut du produit, dans les aides de test si c'est le test.

**Blocked by:**
- External: un run rouge de l'un de ces deux tests avec un journal qui survit à un rechargement (PR 373 fusionnée, fc479f6), ou une reproduction sous charge sur le serveur auto-hébergé (8 brûleurs au plus, 10 minutes au plus par lancement)

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] La cause de chacun des deux échecs est établie sur un échec réel avec le journal, pas supposée
- [ ] Le correctif est posé et les deux tests passent sur plusieurs lancements de CI
