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

## Decision (Mira, PR chat-box/122)

`open_with_comment(tab, md, ...)` takes `md=None`: the file the site fixture wrote stays as it is. Per group:

- **Converted (md=None):** the setups that write one comment on `tab.site.file` and open the tab at once: test_page_chat_box (`open_thread` and seven tests), test_page_dictation (`open_thread`), test_mount_dictation (the proxy-mode test), test_page_agent (the running-Tell test). Twelve setups, behaviour unchanged. In the long-comment test of test_page_chat_box the viewport is now set before the write instead of between the write and the open: nothing reads the file in between.
- **Left as is, `front` fixture** (test_mount_dictation, two tests): `front` is the mounted front, not a `Tab`; the helper opens `tab.open().page` and writes through `tab.site`.
- **Left as is, `doc` fixture** (test_page_mode_toggle): the page is already open when the comment is written and the test waits for the reload; the helper opens after the write, which would remove the thing under test.
- **Left as is, setup between the write and the open** (test_page_waiting_tell `ask_agent`, test_page_work `as_member`, test_page_agent `with_lines`): the hub or the routes are changed after the comment is written and before `open()`; the helper opens inside itself, so these would need a `before_open` hook for three call sites.
- **Left as is, more than one comment, a reply or a status** (test_page_agent replies and `waiting_tell`, test_page_chat_box `set_status` and reply setups, test_page_dictation line 479, test_page_writing, test_page_mobile_composer): the helper adds one comment and no more.

