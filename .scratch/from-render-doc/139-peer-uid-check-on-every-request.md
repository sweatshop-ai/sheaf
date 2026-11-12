# 139: Check the connection's OS user on every cookie and key request

**Status:** open (design ruled, probe 2 run, nothing built; one decision open)

**From:** render-doc ticket 139 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/peer.py` (the nonce-only check), `src/sheafmd/hub/handler.py:716-719`, `tests/test_hub_peer.py:308`, `SPEC.md:877`

**Size:** one decision and one probe before the build; the build is several sessions. Closes the peer-check items of ticket 99.

Today only `/_/open?nonce=` checks who owns the connection. `SPEC.md:877` says the cookie and the key are not checked against the connection's user, and `tests/test_hub_peer.py:308` (`test_a_cookie_route_does_not_look_up_the_connection_yet`) pins that.

- [ ] **Decide first.** Probe 2 (a Playwright test that sends a comment and navigates away in the same tick, against a hub that checks the peer uid on every cookie request) showed typed text is lost when the hub reaches the lookup about 0.3 s late: the closed client's socket reads as uid 0 in FIN_WAIT2 and the save gets 403 (30 of 30 lost). Choose between:
  - (a) accept the limit and write in SPEC 9.6 that a cookie or key leaked to another local user works from that user's account, or
  - (b) an accept()-time variant: look up the owner before reading the request, and answer a client that already closed with `503 try again` and the write not applied, never 403.

- [ ] **Probe 1, not run.** With an `ssh -L` tunnel to a remote hub and a browser through it, `ss -tne state established '( dport = :<hub port> )'` must show the hub's own uid for the forwarded connection. If it shows another uid (for example root), every tunnelled browser would be refused and the check must not be built as designed.

- [ ] **If built (option b):**
  - one lookup per connection, kept on `server._Http`, asked in `Handler._route` after the credential is accepted and before the body is read;
  - `/_/health` never looked up; key, cookie and `/_/open?key=` checked; MCP tokens not checked;
  - only the hub's own uid passes (root refused); unknown cases refuse;
  - the answer is 403 (JSON, or a small page for HTML) naming no uid or path; a rate-limited `peer-refused` diagnostics row;
  - a start-up self-test that turns the check off with a `peer-check-off` row and a notice where owners cannot be read (and makes the nonce check follow it);
  - `sock_diag` (AF_NETLINK, SOCK_DIAG_BY_FAMILY) first, `/proc/net/tcp*` as fallback, in `src/sheafmd/hub/peer.py`;
  - the proxy socket (which already uses SO_PEERCRED) untouched, and the loopback port of a proxy-mode hub checked against the hub's uid, not the proxy user's.

- [ ] **Tests and SPEC for the build.** Turn `tests/test_hub_peer.py:308`; update SPEC 9.1, 9.3, 9.6, 9.9 and the README sentence, which today send a relay running as another user to `sheaf signin-url` (that advice stops working).

- [ ] **By hand after the build.** A second real OS user gets 403 and a `peer-refused` row with both uids and no `Set-Cookie`; a browser through `ssh -L` signs in and saves.
