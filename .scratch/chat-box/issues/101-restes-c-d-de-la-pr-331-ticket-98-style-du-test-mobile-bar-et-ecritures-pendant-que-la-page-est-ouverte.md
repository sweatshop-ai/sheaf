# 101: Restes c et d de la PR 331 (ticket 98): docstring du test mobile_bar, helper d'installation partagé, une garde par un formulaire ouvert

**What to build:** Restes de la revue Opus de la PR 331, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-98-reviews/opus-round1.md`. Ni a ni b.
- Reste c (note, pas de correctif) : `tests/page/test_page_writing.py:3440` recharge juste après `delete_the_thread` ; ce n'est sûr que parce que le formulaire resté ouvert retient le rechargement (`page.js:1532`).
- Reste d : la docstring de `test_page_mobile_bar.py:43-44` décrit une fixture que le test n'utilise plus (une proposition suffirait) ; `:45-47` répète l'installation de `test_page_mobile_refocus.py:28-31` (un helper `phone_with(...)` partagé, déjà proposé au ticket 98) ; `test_page_keyboard.py:188` prend `site` à part là où les voisins font `site = touch_tab.site`.

**Blocked by:** none
