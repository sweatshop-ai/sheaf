# 139: Check the connection's OS user on every cookie and key request

**Claimed by:** Rhea 2026-11-22

**Status:** in-progress (item 1: PR #488; item 2 merged as #509 (39e0f70a); item 3 on branch `sigrid/139-spec`, PR not yet opened; the by-hand check is open)

**Blocked by:** none

**From:** render-doc ticket 139 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/peer.py` (the nonce-only check), `src/sheafmd/hub/handler.py:716-719`, `tests/test_hub_peer.py:308`, `SPEC.md:877`

**Size:** one decision and one probe before the build; the build is several sessions. Closes the peer-check items of ticket 99.

Today only `/_/open?nonce=` checks who owns the connection. `SPEC.md:877` says the cookie and the key are not checked against the connection's user, and `tests/test_hub_peer.py:308` (`test_a_cookie_route_does_not_look_up_the_connection_yet`) pins that.

- [x] **Decide first.** The owner chose (b), the accept()-time lookup with `503 try again`, on 2026-11-20. Probe 2 (a Playwright test that sends a comment and navigates away in the same tick, against a hub that checks the peer uid on every cookie request) showed typed text is lost when the hub reaches the lookup about 0.3 s late: the closed client's socket reads as uid 0 in FIN_WAIT2 and the save gets 403 (30 of 30 lost). Choose between:
  - (a) accept the limit and write in SPEC 9.6 that a cookie or key leaked to another local user works from that user's account, or
  - (b) an accept()-time variant: look up the owner before reading the request, and answer a client that already closed with `503 try again` and the write not applied, never 403.

- [x] **Probe 1, run 2026-11-20: passes.** With an `ssh -L` tunnel to a remote hub and a browser through it, `ss -tne state established '( dport = :<hub port> )'` must show the hub's own uid for the forwarded connection. If it shows another uid (for example root), every tunnelled browser would be refused and the check must not be built as designed.
  Result: a listener on t-compute, an `ssh -L` tunnel from the laptop and a curl through it; on t-compute `ss -tne state established '( dport = :38461 )'` showed the forwarded connection as `uid:1000` (the login user, `session-4740.scope`), not root. The uid is the login user's: a tunnel logged in as another user than the hub's is refused. Probed with a Python listener, not a real hub or browser.

- [x] **If built (option b):** built in #509 (merged 39e0f70a).
  - one lookup per connection, kept on `server._Http`, asked in `Handler._route` after the credential is accepted and before the body is read;
  - `/_/health` never looked up; key, cookie and `/_/open?key=` checked; MCP tokens not checked;
  - only the hub's own uid passes (root refused); unknown cases refuse;
  - the answer is 403 (JSON, or a small page for HTML) naming no uid or path; a rate-limited `peer-refused` diagnostics row;
  - a start-up self-test that turns the check off with a `peer-check-off` row and a notice where owners cannot be read (and makes the nonce check follow it);
  - `sock_diag` (AF_NETLINK, SOCK_DIAG_BY_FAMILY) first, `/proc/net/tcp*` as fallback, in `src/sheafmd/hub/peer.py`;
  - the proxy socket (which already uses SO_PEERCRED) untouched, and the loopback port of a proxy-mode hub checked against the hub's uid, not the proxy user's.

- [ ] **Tests and SPEC for the build.** Turn `tests/test_hub_peer.py:308`; update SPEC 9.1, 9.3, 9.6, 9.9 and the README sentence, which today send a relay running as another user to `sheaf signin-url` (that advice stops working).

- [ ] **By hand after the build.** A second real OS user gets 403 and a `peer-refused` row with both uids and no `Set-Cookie`; a browser through `ssh -L` signs in and saves.

- [ ] **Minor follow-ups from round 4 on #509** (none fixed there):
  - [ ] `tests/test_hub_peer_gate.py:127` (`test_a_caller_that_closed_before_the_hub_could_say_...`) breaks if the suite runs as root: with `ME == 0` it builds an OTHER_USER refusal with uid 1, which now gets 403, not 503. A root case should use an UNKNOWN refusal.
  - [ ] A root hub and a root client that half-closes still gets `503` on every retry (and a spent nonce on `/_/open?nonce=`). The guard is `os.geteuid() == 0 and closed(sock)` in `peer.look`.
  - [ ] The once-a-minute `peer-refused` throttle is shared across kinds: an UNKNOWN refusal can hold back the row of a later OTHER_USER refusal (with both uids) for up to a minute.
  - [ ] Another user who sends and fully closes before the lookup reads uid 0: 503 and no `peer-refused` row. Nothing is let through, but the attempt never shows in `sheaf diag`.
