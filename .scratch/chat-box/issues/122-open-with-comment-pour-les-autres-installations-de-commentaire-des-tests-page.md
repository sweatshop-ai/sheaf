# 122: `open_with_comment` pour les autres installations de commentaire de `tests/page`

**What to build:** Reste de la PR 349 (ticket 111). Cinq tests de `test_page_keyboard.py` utilisent `open_with_comment`. Les autres installations `update_file(... add_comment ...)` de `tests/page` ne s'y prêtent pas telles quelles :
- elles n'écrivent pas le fichier (il vient du fixture) : test_mount_dictation, test_page_dictation, test_page_waiting_tell, test_page_chat_box ;
- elles utilisent un autre fixture que `tab` (`doc`, `front`, `site`) : test_page_mode_toggle, test_mount_dictation ;
- elles ajoutent d'autres réponses ou posent des routes avant l'ouverture : test_page_agent, test_page_work, test_page_chat_box (`set_status`).
Décider pour chaque groupe : un paramètre `md=None` (ne pas écrire), ou laisser tel quel. Comportement inchangé.
Revue de la PR 349 : classes c1, c2, d1 seulement (une remarque d'ordre sans effet, une docstring de 143 caractères), rien à corriger.

**Blocked by:** none

**Claimed by:** Mira

**Status:** ready-for-agent
