# 20: La réponse que le hub a prise n'apparaît pas dans la boîte quand la page abandonne l'envoi, de temps en temps en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_writing.py::test_a_reply_the_hub_took_and_told_of_before_the_page_gave_up_goes_from_the_page_when_it_gives_up`.

**Blocked by:**
- 04

**Claimed by:** Birgit 2026-11-11 12:58

**Status:** in-progress

Run 42923857640 tentative 2 : la boîte montre le fil sans la réponse (« Why apples? / Send reply »), le fichier la contient, le stockage de la page est vide : le formulaire est parti et la réponse n'est pas affichée. Le `BrokenPipeError` du hub est dans la section « Captured stderr teardown » : le relâchement de la requête retenue à la fin du test ; le `no running event loop` est un avertissement Playwright attaché à un autre test (`test_a_text_sent_again_after_a_give_up…`). Ni l'un ni l'autre n'est la cause. Non reproduit en local ; le test s'appuie sur `p.clock` (horloge simulée), à examiner.

- [x] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [x] Le correctif traite la cause, pas un délai ou une relance

**Cause (preuve, 2026-11-11).** Défaut du test, pas de la page. `p.clock` n'y est pour rien en soi. Quand le flux de la page dit `hello` pendant que l'envoi est dehors (sur un runner chargé le premier `hello` arrive tard), `meetHello` demande un `checkText`, remis à la fin de l'envoi (`checkAgain`). À l'abandon, `replayHeld` lance cette vérification et garde l'événement `changed` de l'écriture (`heardAfterCheck`) jusqu'à sa réponse ou `CHECK_WAIT` (10 s). La réponse de `/_/doc` attend le verrou que le hub tient jusqu'au `release()` du test : seule la fin de `CHECK_WAIT` libère l'événement, plus longue que les 8 s du test. Le stockage est déjà vide parce que `taken()` s'exécute à l'arrivée de l'événement, d'où « le fichier a la réponse, le stockage est vide, la boîte n'a pas la réponse ». Reproduit à la demande : un `hello` publié par le hub pendant l'envoi retenu donne `timed out waiting for the reply in its thread` (et le `BrokenPipeError` de la section teardown, qui n'est que le relâchement).

**Correctif.** Le test fait avancer l'horloge de la page de la durée de `CHECK_WAIT` après l'abandon, et passe deux fois, sans puis avec le `hello` (paramètre). Rouge sans l'avance avec `hello`, vert avec.

**Note, pas un défaut ouvert.** En production la même attente borne à 10 s l'affichage d'une réponse déjà reçue quand une vérification attend le verrou d'une écriture très longue ; aucune donnée n'est perdue. Je ne la change pas ici.

- [ ] CI verte sur trois passages de suite
