# Open WebUI's admin can read the client users' chats on the client tiroirs

**What to do:** On tiroir-chienvert (root@100.92.216.109) and tiroir-respace (root@100.68.84.43), Open WebUI runs with no `ENABLE_ADMIN_*` env, so its defaults hold: `ENABLE_ADMIN_CHAT_ACCESS`, `ENABLE_ADMIN_EXPORT` and `ENABLE_ADMIN_WORKSPACE_CONTENT_ACCESS` are True (`/app/backend/open_webui/env.py:371`, `config.py:2082-2084`, checked 2026-11-16). Thierry (`thierry@thinkingtoo.com`) is admin on both, so the admin panel opens Gil's, Pierre's and Zoya's chats. Thierry's rule (2026-11-16, wayfinder `sheaf-in-open-webui` ticket 22): every client user's brain, chats and private pages are private, and the agency never reads them. Through a stage per box (`/root/stage-<name>-<date>/`, MANIFEST, preflight, apply, rollback, backup read back first), set the three to `False` and move ThinkingToo accounts to the `user` role. Some account must stay admin to manage users (the open question in ticket 22 on who administers a client tiroir); settle that before demoting Thierry. tiroir-avetta was not reachable over ssh on 2026-11-16 and its users were not checked; its record is `sweatshop-ai/tiroir-avetta`.

**Blocked by:** ticket 22 of `sheaf-in-open-webui` for who stays admin; the env change itself is blocked by nothing.

**Status:** open

- [ ] chienvert, respace, avetta: the three `ENABLE_ADMIN_*` are `False`, read back from the running container
- [ ] no ThinkingToo account is `admin` on a client tiroir, or the one that stays is the one ticket 22 names
- [ ] the client tiroir runbook (`thinkingtoo/clients/_template/tiroir`) sets the three to `False` for every new client tiroir
