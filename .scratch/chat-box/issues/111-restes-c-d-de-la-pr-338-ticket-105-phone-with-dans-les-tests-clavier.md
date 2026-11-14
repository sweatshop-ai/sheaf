# 111: Restes c et d de la PR 338 (ticket 105): `phone_with` dans les deux tests clavier, doublon d'explication, nom de l'aide

**What to build:** Restes de la revue Opus de la PR 338, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-105-reviews/opus-round1.md`. Ni a ni b (le b a été corrigé dans la PR).
- Reste c1 : deux tests de `tests/page/test_page_keyboard.py` installent la page comme `phone_with` (`FAKE_VV` s'ajoute avant l'appel, `when` couvre leur date) ; il y a 32 installations de ce genre dans `tests/page`.
- Reste c2 : l'explication du ticket 78 figure deux fois, dans la docstring du test clavier et dans `phone_with`.
- Reste d1 : le nom `phone_with` dit téléphone, mais l'aide sert pour n'importe quel onglet.

**Blocked by:** none

**Claimed by:** Nabil
**Status:** done (merged as 07085fa; leftovers in ticket 122)
