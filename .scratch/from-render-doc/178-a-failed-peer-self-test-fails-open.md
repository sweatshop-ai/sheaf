# 178: A Linux hub whose peer self-test fails redeems sign-in nonces from any user

**Claimed by:** Ciro 2026-11-22

**Status:** done (PR #585, merge 1f9d9ef6 on main, head 1e86c1e9; CI ubuntu-24.04 py3.13 success; Codex GO round 2)

**Blocked by:** none

**From:** ticket 99 line 22, the second-opinion security read of the nonce peer check (Codex, 2026-11-22), finding [P1]

**Where:** `src/sheafmd/hub/peer.py` `selftest` (the `except (OSError, ValueError, TypeError)` around the loopback pair) and `startup`; `src/sheafmd/hub/server.py` (`off = peer.startup()` sets `peer_off`; `peer.look` is skipped while it is set); `src/sheafmd/hub/handler.py` `_owner` (`if self.peer_off: return None`)

On Linux the start-up self-test opens a loopback pair and reads its owner. Any `OSError` on the way (no free ephemeral port, no file descriptor left, a netlink or `/proc` read that fails) turns the check off for the hub's whole life, and `/_/open?nonce=` then signs in whoever follows the link, as before 9.1. Another local user can cause such a failure on purpose: hold every port of the ephemeral range on 127.0.0.1 while the hub starts (the hub's own port stays free), let them go, then read the next nonce from `/proc/<pid>/cmdline` of the browser and redeem it, receiving the 400-day cookie. The `peer-check-off` row and the stderr notice (PR #579) tell the owner, but do not close the door.

- [x] Red first: a test where the self-test raises `OSError` on Linux and a nonce redeemed by another uid is still refused (no `Set-Cookie`). Done in 1f9d9ef6: `tests/test_hub_peer_gate.py::test_a_self_test_that_raises_leaves_the_check_on_so_another_users_nonce_signs_no_one_in`.
- [x] Fail closed on Linux: a self-test that raised is retried (at the first nonce, or on a timer), and until a retry succeeds a nonce is refused with a page that names `sheaf signin-url` (the key link, read from a 0600 file, is not exposed to other users). A self-test that answered with a wrong uid stays the documented `peer-check-off`, or is refused the same way: decide and write it in SPEC 9.1. Done in 1f9d9ef6: a self-test that raises leaves the check on and writes a `peer-selftest-failed` row; the leniency ends at the first connection read as the hub's own (the retry); a refused link names `sheaf signin-url` (`test_a_self_test_that_raises_names_signin_url_on_the_page_of_a_link_whose_owner_it_could_not_read`, `test_the_first_connection_read_as_the_hubs_own_ends_the_leniency_a_raised_self_test_allowed`, `test_any_connection_read_as_the_hubs_own_ends_the_leniency_health_included`). Decided: a wrong uid stays the documented `peer-check-off` (SPEC 9.1).
- [x] SPEC 9.1 and 9.6 say which failures turn the check off and which only defer it. Done in 1f9d9ef6: 9.1 (a wrong owner turns it off; a self-test that cannot run leaves it on) and 9.6 (the `403` by-no-one exception while a raised self-test has not yet been followed by an own-connection read).
