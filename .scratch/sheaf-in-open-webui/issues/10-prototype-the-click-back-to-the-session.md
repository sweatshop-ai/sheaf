# 10: How the click on a session's name gets back to the laptop

**Type:** prototype
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

Ticket 09 requires that the session's name on a page or Catalog row served by the tiroir brings Thierry back to that session on his laptop, as `POST /_/jump` (SPEC 8.5, 4.3 `[jump]`/`[reopen]`) does today, where the hub runs a local command to AgentView (`127.0.0.1:8765/api/jump`). On the tiroir the hub never connects to a laptop (9.14) and `/_/jump` answers 404 on the proxy socket. Which way works, tried for real: (a) the page, open in the laptop's browser, calls the local AgentView directly (Chrome's rules for an https page reaching `127.0.0.1`, AgentView's `X-Fleet` check and CORS); (b) a relay the laptop keeps open to the tiroir, laptop-wide rather than per fork (9.14 today), that carries a jump and runs the same `[jump]` command. A throwaway prototype of each, linked from this ticket, for Thierry to try; also what the name does on a device where neither works.

## Prototype

Built 2026-11-15 by Ottilie: branch `prototype/10-jump` (commit f361b9c, pushed, never merged), folder `.scratch/sheaf-in-open-webui/prototype/jump/`. A stand-in tiroir on t-compute (`http://100.117.2.45:8790/`) serves a page with the session's name twice, once per way. Way a has a loopback shim on the laptop standing in for AgentView with CORS (`127.0.0.1:8766`, forwards to `:8765` with `X-Fleet`). Way b has a relay on the laptop that holds a stream open to the stand-in and runs the laptop's own `[jump]` command.

Tried so far (Chrome 156, the professional profile):

- **Way b** carries the jump end to end: page → stand-in on t-compute → the laptop's stream → `[jump]` → AgentView, its answer shown back on the page within a second. It needs nothing from the browser, so it works from any device on which the page opens (the phone included). It needs a laptop process that stays connected, with a token.
- **Way a** works from a tailnet `http://100.x` page with no prompt: preflight, then POST, then AgentView. From the real origin `https://thinkingtoo.tiroir.me` (public IP 204.168.163.67), Chrome holds the request before any preflight leaves: `local-network-access` permission state `prompt`. The member must allow "access devices on your local network" once per tiroir origin, per browser profile. It also only works on the laptop where the session runs.
- **AgentView today** answers a preflight with `501 Unsupported method ('OPTIONS')` and refuses any foreign Origin (403, `_origin_ok`), so way a needs AgentView changes (an allow-listed tiroir origin, an OPTIONS answer with CORS and the local-network header). Way b needs none: the relay calls AgentView locally, as the hub does today.
- Aside, not this ticket's: AgentView answers "no terminal hosts this session" for Ottilie, a session in a WezTerm tab, so its jump fails the same way on the laptop hub today.

Tried with Thierry (2026-11-15, 21:45):

- **Way a from the real origin works once allowed.** In the professional Chrome on `https://thinkingtoo.tiroir.me/list`, Chrome showed its local-network prompt and Thierry allowed it (state `granted`). Clicking "Kenji" then sent preflight and POST to the shim. AgentView answered `{"ok": true, "ran": ["wezterm cli … activate-pane --pane-id 12", "wmctrl -ia …"]}` and Kenji's pane came to the front.
- **The phone is already solved elsewhere** (Thierry): in FleetView on the phone, a click on a session under Remote Control opens it in the Claude app (`agentview/fleet.py` `jump_of`, `remote`; `index.html` `wayOf`: on a touch screen with no hover, the `https://` Remote Control link wins over the pane). Raising a laptop terminal from a phone is no use, so way b's only advantage is moot.
- The stand-in, shim and relay were stopped and t-compute's folder removed afterwards.
