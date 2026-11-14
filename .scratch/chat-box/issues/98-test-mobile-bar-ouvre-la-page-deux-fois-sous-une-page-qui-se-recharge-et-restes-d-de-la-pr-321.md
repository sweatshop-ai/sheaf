# 98: `test_page_mobile_bar.py::test_touching_a_number_puts_the_cursor_in_the_field_too` ouvre la page deux fois sous une page qui se recharge : même instabilité que le ticket 78

**What to build:** Reste c (et d) de la revue Opus de la PR 321 (ticket 78), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-78-reviews/opus-round1.md`.
- Reste c : `tests/page/test_page_mobile_bar.py:42` suit le même schéma que le test corrigé au ticket 78. La fixture `phone` (l. 22) ouvre la page, `update_file` ajoute un commentaire (l. 43), puis `phone.open()` rouvre la page (l. 45). Une page ouverte dont le fichier change se recharge d'elle-même ; le second `goto` peut courir contre ce rechargement (« Navigation ... is interrupted by another navigation to the same URL »). Correctif du ticket 78 : écrire le commentaire avant l'ouverture, ouvrir une seule fois. Non vu en CI à ce jour. Chercher aussi les écritures cachées dans des helpers ou faites par la page, que la revue n'a pas suivies.
- Restes d, au choix : `test_page_keyboard.py:188` prend `site` à part là où les voisins font `site = touch_tab.site` ; les deux lignes d'installation copient la fixture `phone` (un helper `phone_with(...)` servirait aussi mobile_bar) ; la docstring du test corrigé explique une fixture qu'il n'utilise plus (une proposition suffirait).

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent
