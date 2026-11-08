# 13: The names of members and tokens are checked the same way at the start and at `add`

**What to build:** The hub's start check and `sheaf token add` fold names the same way, the start check covers every pair it should, and its refusals are logged and worded for what they are. Closes rows 2, 3, 5, 7 and 8 (#207).

**Where (main fac5160):**
- row 2: `hub/proxy.py:436-456` `check_names`: a member is compared with tokens, not token with token or token with person
- row 3: `hub/proxy.py:431` `same_name` (case only) vs `cli.py:900-907` `_agent_clash` using `name_key` (case, accent, width); `cli.py:880-881` uses `same_name`
- row 5: `hub/proxy.py:455` refuses only a member name ending in `(action)`, not a built `<client> (action)` 
- row 7: `hub/server.py:415-418` `_proxy_refused` logs every refusal as `proxy-config`; `hub/proxy.py:464-466` says "another member"
- row 8: `hub/server.py:468` `config.user_name()` runs once per token row

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session (proxy.py, server.py, tests/test_proxy_config.py, tests/test_proxy_start.py)

- [ ] Test first (3): names that differ only by accent or width are one name in both `check_names` and `add`; a hub whose config `add` accepted always starts, and the reverse
- [ ] Test first (2): two old tokens, and a token and the person, that sign the same name, are refused at the start with a message that names both (old tokens may still share a display if SPEC 9.7 says so: read it, say which in the PR)
- [ ] Test first (5): a client `action` (or a role word) in an agent's built name is refused at `token add` and at the start
- [ ] Test first (7): a refusal from `check_agent_names` is logged under its own label and its message does not offer "another member" in loopback
- [ ] Test first (8): `config.user_name()` runs once; an unknown config key warns once
- [ ] The existing start tests (`tests/test_proxy_start.py`) stay green
