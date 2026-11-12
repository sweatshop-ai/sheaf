# 31: Le test « une réponse d'action met fin à l'attente » lit la ligne d'attente pendant une navigation de la page, de temps en temps en CI

**What to build:** `tests/page/test_page_waiting_tell.py::test_an_action_reply_ends_the_wait` a échoué sur main (run 43212771285, tête 597d52a = PR #247, job 131164313675, tranche 2/3, py3.13, 2026-11-12 vers 12:01 UTC : `1 failed, 326 passed`). Le test s'arrête ligne 69, `until(lambda: line(tab) == [], what="the line to go on the action reply")`, avec `playwright._impl._errors.Error: Locator.all_inner_texts: Execution context was destroyed, most likely because of a navigation`, levée dans l'aide `line()` (ligne 28 : `tab.page.locator("#rd-popover .rd-waits").all_inner_texts()`).

**Blocked by:** 04

**Claimed by:** Elif 2026-11-12 13:52

**Status:** in-progress

**Ce qui ne va pas (une lecture, pas une preuve) :** la page navigue (rechargement) pendant que le test sonde `line()` ; l'appel `all_inner_texts` n'a aucune garde contre une navigation, et l'erreur de Playwright sort de `until` au lieu d'être sondée à nouveau. C'est la famille des tickets 17, 18 et 24. Le correctif de ces tickets n'a pas touché ce test. La relance du run n'a pas été faite ; le même test est vert sur le run de la PR #244 (43219440986, tête 35cf561), un seul passage, ce qui n'en dit pas plus. Les PR #246 et #247 (CI en 4 workers xdist, garde d'import) ne touchent ni `src/`, ni `page.js`, ni ce test ; la mise en 4 workers élargit peut-être les fenêtres de temps, ce qui n'est pas montré. À établir d'abord : ce qui fait naviguer la page à ce moment du test (un rechargement voulu par la page à la réponse de type `action`, ou un rechargement de la fixture).

- [ ] La cause est écrite avec la preuve (la sortie de la CI qui l'a relevée, plus ce qui fait naviguer la page)
- [ ] Le correctif traite la cause (attendre la fin de la navigation, ou lire la ligne dans un seul `evaluate` qui reprend après une navigation), sans délai fixe ni relance aveugle ; si la page navigue sans raison, la cause est cherchée dans le code
- [ ] La même lecture sûre sert aux autres tests du fichier qui sondent `line()`
- [ ] CI verte sur deux passages de suite
