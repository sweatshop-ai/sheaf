# 20: La réponse que le hub a prise n'apparaît pas dans la boîte quand la page abandonne l'envoi, de temps en temps en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_writing.py::test_a_reply_the_hub_took_and_told_of_before_the_page_gave_up_goes_from_the_page_when_it_gives_up`.

**Blocked by:**
- 04

**Status:** ready-for-agent

Run 42923857640 tentative 2 : la boîte montre le fil sans la réponse (« Why apples? / Send reply »), le fichier la contient, le stockage de la page est vide : le formulaire est parti et la réponse n'est pas affichée. Le `BrokenPipeError` du hub est dans la section « Captured stderr teardown » : le relâchement de la requête retenue à la fin du test ; le `no running event loop` est un avertissement Playwright attaché à un autre test (`test_a_text_sent_again_after_a_give_up…`). Ni l'un ni l'autre n'est la cause. Non reproduit en local ; le test s'appuie sur `p.clock` (horloge simulée), à examiner.

- [ ] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [ ] Le correctif traite la cause, pas un délai ou une relance
- [ ] CI verte sur trois passages de suite
