# 127: Restes c, d de la PR 354 (tickets 122, 123) : le groupe « installation entre l'écriture et l'ouverture »

**What to build:** Revue Opus de la PR 354 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-122-reviews/review-1.md`), classes c et d, rien de classe a. Au choix :
1. Le groupe « installation entre l'écriture du commentaire et l'ouverture » (test_page_agent `with_lines` et `waiting_tell`, test_page_work `as_member`) pourrait passer à `open_with_comment(tab, None, ...)` sans crochet `before_open` : `with_lines` (routes de la page), `as_member` (patch de `site.hub.page`) et l'écriture du fichier de config ne touchent pas le document ; il suffit de les placer avant l'appel, comme la PR l'a fait pour `set_viewport_size`. `ask_agent` (test_page_waiting_tell) change l'état du hub sur le document : le laisser.
2. Le test `test_a_thread_on_a_page_that_cannot_save_...` (test_page_chat_box.py, ~:713) n'est dans aucun groupe du ticket 122 : il ouvre une copie `file://` par `context.new_page()`, pas `tab.open()`. L'exclusion est juste ; une ligne dans le ticket 122 suffit.
3. La ligne d'import de test_page_chat_box.py:6 fait 135 caractères ; aucune règle de longueur.

**Blocked by:** PR 354

**Status:** ready-for-agent
