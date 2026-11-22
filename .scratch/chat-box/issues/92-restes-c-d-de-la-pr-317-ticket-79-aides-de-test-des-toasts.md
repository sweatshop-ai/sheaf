# 92: Restes c/d de la PR 317 (ticket 79) : aides de test des toasts, un toast déjà parti compté comme dit, et deux détails de style

**What to build:** Restes de la revue Opus de la PR 317 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-79-reviews/opus-review.md`), aucun de classe a ou b.

- **(d)** `tests/page/pagehelp.py`, `toasts_to_the_end` : `#rd-toast` garde son texte quand sa classe `show` est retirée, et `look()` note le texte avant de regarder si un toast est à l'écran. Un deuxième appel, la file finie, rend donc le dernier toast (`['The text changed while you wrote.']` sur la fausse page de test) : une assertion « ce toast n'est pas dit » peut échouer sur un toast dit à juste titre plus tôt. À faire : ne noter le texte que lorsqu'un toast est à l'écran, avec un test de la fausse page `QueuedToasts`.
- **(d)** Sur horloge en pause, chaque tour de `toasted(on_clock=True)` / `toasts_to_the_end(on_clock=True)` fait avancer de 250 ms (`TOAST_STEP`) ; passer un toast rouge puis un de 2,6 s prend environ 39 tours, et chaque `clock.run_for` de Playwright ajoute un script d'initialisation au contexte. Non mesuré. À faire : mesurer sur le serveur auto-hébergé, et pas plus grand si le gain est nul (un toast reste au moins 2,6 s à l'écran, donc un pas de 1 s ne laisserait passer aucun toast).
- **(c)** `tests/page/test_page_writing.py:2685` : le lambda `toast_state(p)[1] and run_clock(p, TOAST_STEP)` ne marche que parce que `run_clock` rend `None`. Une `def` nommée le dirait. 
- **(c)** `tests/page/test_page_writing.py:13` : `run_clock, TOAST_STEP` ajoutés après `until` sur une ligne déjà plus large que le reste du fichier.
- **(c)** `tests/page/test_page_waits.py` : `toast_text()` est une aide d'une ligne, entre deux tests, utilisée une fois ; `page.text` fait la même chose.

**Blocked by:** PR 317


**Claimed by:** Anselm 2026-11-14 19:33

**Status:** done, merge dc62826

**Par où commencer :** `tests/page/pagehelp.py`, `toasts_to_the_end`.

- [x] `toasts_to_the_end` ne rend que les toasts qui ont été à l'écran depuis l'appel — PR 330 (dc62826) : `tests/page/pagehelp.py:340` ne note le texte que si `up` ; tests `tests/page/test_page_waits.py:183` et `:190`
- [x] Le pas de l'horloge est mesuré, et gardé ou changé avec la mesure — mesuré sur le serveur auto-hébergé (7,5 s à 250 ms, 7,0 s à 1000 et 2000 ms : pas de gain), gardé à 250, mesure écrite dans le commentaire de `tests/page/pagehelp.py:304-306`
- [x] Les trois détails de style sont repris — `tests/page/test_page_writing.py:2704` (`def taken_or_gone`), `:14` (import sur sa propre ligne), `tests/page/test_page_waits.py:169` (`page.text`, `toast_text` supprimée)
