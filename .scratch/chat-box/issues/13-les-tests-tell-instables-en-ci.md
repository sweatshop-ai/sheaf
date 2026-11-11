# 13: Les tests de la famille Tell échouent de temps en temps en CI

**What to build:** Trouver la cause de quatre échecs CI intermittents autour d'un Tell, qui ne sont pas celui d'Échap (ticket 10, cause trouvée et corrigée). Aucun ne touche le hub ni `fillPopover` : la PR #240 (`chat-box/05`) les montre aussi.

**Blocked by:**
- 04

**Status:** ready-for-agent

Échecs relevés (aucun reproduit en local) :

- `test_page_writing.py::test_a_tell_or_cancel_the_hub_cannot_be_reached_for_says_that_it_did_not_go_out[cancel-tell]` : l'attente du toast expire (8 s). PR #241 run 42925663097 tentative 1 ; PR #240 run 42923857640 tentative 1 ; t-compute à 9aed290 (ticket 03). Le test relève maintenant le nombre de requêtes `/_/cancel` refusées, les toasts vus et le texte de la boîte : le prochain rouge dit si le clic est perdu (0 requête) ou si le toast est remplacé (≥ 1).
- `test_page_waiting_tell.py::test_tell_waits_then_is_seen_and_the_line_survives_a_reload` : la ligne « vu » n'arrive pas (PR #240, run 42923857640, tentative 1).
- `test_page_writing.py::test_send_and_tell_starts_one_tell_and_the_thread_waits_for_its_reply` : `assert [] == ['and plums?']` (même run).
- `test_page_writing.py::test_a_reply_the_hub_took_and_told_of_before_the_page_gave_up_goes_from_the_page_when_it_gives_up` (tentative 2 du même run) : la boîte ne montre pas la réponse, le fichier la contient, le stockage de la page est vide. Le `BrokenPipeError` du hub est le relâchement de la requête retenue au démontage, et `no running event loop` est un avertissement de Playwright au démontage d'un autre test : tous deux du bruit, pas la cause.

- [ ] Pour chaque test, la cause est écrite avec la preuve (un échec reproduit à la demande, comme pour Échap, ou la sortie d'une CI qui l'a relevée)
- [ ] Le correctif traite la cause, pas un délai ou une relance
- [ ] CI verte sur trois passages de suite
