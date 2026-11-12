# 24: Le test du « moins » lit la valeur d'un champ que la boîte vient de fermer, de temps en temps en CI

**What to build:** `tests/page/test_page_chat_box.py::test_the_minus_resolves_an_open_thread_and_stays_while_writing` a échoué sur main (run 43180594189, py3.11, 2026-11-12 08:45 UTC, 7dae7b2) avec `pagehelp.PageStalled: timed out waiting for the box to close (the page did not answer)`, ligne 115.

**Blocked by:**
- 04

**Claimed by:** Elif 2026-11-12

**Status:** in-progress

La ligne attendue est `not p.is_visible("#rd-popover textarea") or p.input_value("#rd-popover textarea") == ""`. Le fichier avait déjà `resolved` (la ligne 114 est passée). `is_visible` voit le champ, la boîte se ferme, puis `input_value` attend un champ qui n'existe plus (30 s par défaut chez Playwright) jusqu'à ce que la garde `stalls_after` coupe l'attente : c'est `PageStalled`, pas le « timed out » ordinaire de `until`. Cause lue dans le code et dans le message de l'échec, non reproduite en local.

- [x] La cause est écrite avec la preuve (la sortie de la CI qui l'a relevée)
- [x] Le correctif traite la cause : un seul `evaluate` lit la présence, la visibilité et la valeur du champ, sans fenêtre entre deux appels
- [x] CI verte sur deux passages de suite : runs 43190504226 sur 08c8883 et 43201969936 sur 4455590, chacun vert aux tentatives 1 et 2
