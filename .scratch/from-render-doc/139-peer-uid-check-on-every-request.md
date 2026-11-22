# 139: Check the connection's OS user on every cookie and key request

**Claimed by:** Rhea 2026-11-22

**Status:** in-review (the build merged as #509; the SPEC and tests are on main as 494ee891; the round-4 follow-ups are in PR #572 (review GO, CI running); the by-hand check passed on 2026-11-22)

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

- [x] **Tests and SPEC for the build.** Turn `tests/test_hub_peer.py:308`; update SPEC 9.1, 9.3, 9.6, 9.9 and the README sentence, which today send a relay running as another user to `sheaf signin-url` (that advice stops working).
  Evidence: on main as 494ee891 (SPEC 9.1, 9.3, 9.6, 9.9 and README). The pinned test was turned in #509 (`test_a_connection_the_server_did_not_look_at_is_not_judged_by_a_key_or_a_cookie`, plus `tests/test_hub_peer_gate.py`). The peer test files gave 58 passed on main. The branch `sigrid/139-spec` (27763476) is empty against main.

- [x] **By hand after the build.** A second real OS user gets 403 and a `peer-refused` row with both uids and no `Set-Cookie`; a browser through `ssh -L` signs in and saves.
  Evidence, 2026-11-22, on the CI runner host: a scratch hub with the PR #572 code, its own SHEAF_HOME and port, running as uid 1000. Requests with the key:
  - as the hub user: 200;
  - as `nobody` (uid 65534): `403` with "this hub answers only to the user that runs it" and no `Set-Cookie`;
  - as `nobody` via `/_/open?key=`: `403` with no `Set-Cookie`.
  One `peer-refused` row was written, with `peer_uid: 65534, hub_uid: 1000`. A Chrome on the laptop went through an `ssh -L` tunnel, signed in with `sheaf signin-url`, and an edit was saved to the document on disk. `ss` showed the forwarded connections as uid 1000. The second user was the existing `nobody` account, because creating a test account was refused.

- [x] **Minor follow-ups from round 4 on #509** (none fixed there). All four were fixed in PR #572 (819e638e). The touched test files `tests/test_hub_peer.py`, `tests/test_hub_peer_gate.py`, `tests/test_hub_peer_lookup.py` and `tests/test_public_tree.py` gave 115 passed and 1 skipped.
  - [x] `tests/test_hub_peer_gate.py:127` (`test_a_caller_that_closed_before_the_hub_could_say_...`) breaks if the suite runs as root: with `ME == 0` it builds an OTHER_USER refusal with uid 1, which now gets 403, not 503. A root case should use an UNKNOWN refusal.
  - [x] A root hub and a root client that half-closes still gets `503` on every retry (and a spent nonce on `/_/open?nonce=`). The guard is `os.geteuid() == 0 and closed(sock)` in `peer.look`.
  - [x] The once-a-minute `peer-refused` throttle is shared across kinds: an UNKNOWN refusal can hold back the row of a later OTHER_USER refusal (with both uids) for up to a minute.
  - [x] Another user who sends and fully closes before the lookup reads uid 0: 503 and no `peer-refused` row. Nothing is let through, but the attempt never shows in `sheaf diag`.
    Fixed this way. A socket that no process holds (inode 0) is never taken for the hub's user. Where /proc still names the other user's uid, the answer is 403 with a row. Where it does not, the answer is 503 with no row, as SPEC 9.6 states, and nothing is let through.
  - Items 1 to 3: the root case uses an UNKNOWN refusal; the root guard was replaced by the inode check, so a half-closed root client to a root hub is judged by its owner; the throttle is now per kind.

- [ ] **Follow-up from the #572 review (minor, not fixed).** `src/sheafmd/hub/handler.py` `_gate`: the `or no.uid == 0` clause in the 503 condition is redundant now. As a result, a root caller that only half-closed to a non-root hub gets 503 instead of 403 plus a row. Nothing is let through.
