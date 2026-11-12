# 10: Le test d'Échap échoue de temps en temps en CI : trouver la cause

**What to build:** Le test d'Échap (keep / drawKept / closePopover) échoue parfois en CI alors qu'il passe sur un portable. La cause n'est pas établie. Issu de la review du bug hunt de la PR #238 (P2 n° 4) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:**
- 04

**Claimed by:** Isolde 2026-11-12 10:01

**Status:** in-progress

**Ce qui ne va pas :** le test d'Échap. Ses assertions sont saines et la review n'a trouvé aucun bug de produit qui perde des données : Échap seul ne peut ni quitter la boîte ni la redessiner. Le commit `54abdda` n'a ajouté que des diagnostics : à l'échec, le test imprime ce que la page contenait (la boîte et ses formulaires, quand `#rd-popover` a été retiré ou ajouté, le stockage). Un `POPOVER_STATE` sans clé `log` veut dire que la page s'est rechargée. À lire à la prochaine occurrence, avant toute hypothèse.

- [x] Au prochain échec en CI, la sortie de `54abdda` est lue et la cause écrite dans ce ticket avec la preuve (ci-dessous)
- [x] Le correctif traite cette cause, pas un délai ou une relance
- [x] Si la cause est un défaut du test, il est corrigé ; si c'est un défaut du produit, un ticket à part est ouvert (défaut du test ; les autres tests Tell : tickets 17 à 20)
- [x] Les diagnostics de `54abdda` sont retirés ou gardés, avec la raison (gardés, ci-dessous)

**Cause (preuve, 2026-11-11).** Run 42925663097, tentative 2 : `{"log": [["removed", 1], ["added", 5, false]], ...}`. Échap retire `#rd-popover` à 1 ms, et 4 ms plus tard une boîte sans `data-kept` est ajoutée : c'est le formulaire que l'envoi échoué ramène à son fil. `fail_a_reply` attendait `#rd-popover textarea`, que le formulaire de l'envoi encore en cours satisfait déjà ; le test vidait le champ et appuyait sur Échap avant que la page ait appris l'échec. Sur un portable l'échec arrive avant ; sur un runner chargé, après. Reproduit à la demande : un `fetch` dont le rejet arrive 400 ms plus tard donne `{"log": [["removed", 13], ["added", 303, false]], "box": true}`. Ce comportement de la page (un envoi échoué rend son formulaire à son fil, même fermé) est voulu : la page n'a pas de défaut.

**Même cause, une étape plus loin.** PR #240, run 43001211278 (11faedf) : `popover_goes` passe, puis `wait_for_selector("#rd-popover .rd-scroll")` expire après le clic sur le badge. L'échec tardif rouvre la boîte dans l'intervalle que `popover_goes` traverse, et le clic sur le badge la referme. Cohérent avec la cause ci-dessus ; non reproduit à cette étape.

**Correctif.** `fail_a_reply` attend le toast « did not go out » avant de rendre la main. Le test d'Échap retarde le rejet de 400 ms et vérifie 600 ms après Échap que la boîte ne revient pas : rouge sans l'attente du toast (`the box came back after Escape`), vert avec.

**Diagnostics de `54abdda`.** Gardés (`popover_goes`) : ils ont servi à lire cette cause.

**Le test du toast d'annulation (`cancel-tell`).** Même famille d'échec en CI mais pas la même cause : il n'appelle pas `fail_a_reply`, et l'attente du toast a expiré sans qu'on sache si la requête est partie. Il ne se reproduit pas en local (12 passages). Le test relève maintenant le nombre de requêtes refusées et les toasts vus ; la suite est le ticket 17.

- [ ] CI verte sur trois passages de suite

**CI après la fusion de #241 (2026-11-12).** Fusion `7dae7b2` : le run push 43103207367 est vert. Le run planifié 43180594189 sur le même sha échoue sur py3.11 (py3.13 et py3.14 verts), deux tests de page : `test_the_minus_resolves_an_open_thread_and_stays_while_writing` (`test_page_chat_box.py`, pas encore tracé) et `test_send_and_tell_starts_one_tell_and_the_thread_waits_for_its_reply` (`test_page_writing.py:2198`, `[] == ['and plums?']`, la famille des tickets 17 à 20). Ni l'un ni l'autre n'est le test d'Échap de ce ticket : `test_escape_is_minimize` et `test_a_reply_or_edit_whose_send_fails_after_escape_or_a_click_outside_comes_back_with_its_text[reply-Escape]` passent dans ce même run. La dernière case reste ouverte : un seul run push vert contient le correctif, le run planifié du même sha est rouge, et trois passages de suite ne sont pas atteints.
