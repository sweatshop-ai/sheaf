# 99: Lifecycle review follow-ups: peer check, restart announcements, stop races, refactors, lint

**Status:** open

**From:** render-doc ticket 99 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/peer.py`, `src/sheafmd/hub/handler.py:52-68`, `:320`, `:700-725`, `src/sheafmd/lifecycle.py`, `src/sheafmd/hub/core.py:1307-1346`, `src/sheafmd/hub/client.py:381`, `:418`, `src/sheafmd/cli.py`, `src/sheafmd/hub/service.py`, `src/sheafmd/paths.py:71-77`, `SPEC.md:877`

**Size:** many small items; the peer-check ones close with ticket 139

## Peer check

- [ ] **The peer-uid check on every cookie and key request is not built.** Today only `/_/open?nonce=` is checked (`src/sheafmd/hub/peer.py:94-122`, called from `src/sheafmd/hub/handler.py:716-719`); `SPEC.md:877` says so. The full design and its open decision are in ticket 139; these items close with it: a missed row on a busy machine (`_owners`, `peer.py:75-85`, reads `/proc/net/tcp*` whole instead of asking the kernel with NETLINK_SOCK_DIAG); a closed client reading as uid 0 (`_owners` matches the two ends with no TCP-state filter); a relay running as another user is a dead end (`handler.py:60-68`, `LINK_OTHER_USER` has no way in, `LINK_UNKNOWN` names `signin-url`); macOS or a Linux without `/proc/net` behaving differently (`peer.py:48-50`, `supported()` is Linux only).
- [ ] **By hand, never done:** a `sheaf open` link followed by a second real OS user must get 401, no `Set-Cookie`, and an `open-401` diagnostics row naming both uids; and a browser through `ssh -L` to a remote hub signing in.
- [ ] **`LINK_USED` advises `sheaf rotate` even on Linux** (`src/sheafmd/hub/handler.py:52-56`, used at `:716`), where the peer check means another user could not have taken the cookie. Decide whether the Linux page drops that advice.
- [ ] **The no-peer-check warning shows only after a failure.** On platforms where the peer check cannot run, `LINK_LIMIT` (`handler.py:57-59`) appears only on the page of a link that failed; decide whether `sheaf open` prints it on every run there.
- [ ] Optional: a second-opinion security read of the nonce peer check (`src/sheafmd/hub/peer.py` and the `/_/open` path in `src/sheafmd/hub/handler.py:700-725`); never done on the merged code.

## Restart and stop

- [ ] **`/_/restarting` has no generation.** Two overlapping `sheaf restart` runs let A's `DELETE /_/restarting` clear B's newer announcement (`src/sheafmd/lifecycle.py:117`, `:149`; `src/sheafmd/hub/core.py:1327-1337`). Fix idea: a token returned by `POST` and required by `DELETE`.
- [ ] **A lost answer to `POST /_/restarting` leaves the announcement up.** If the POST succeeds on the hub but its answer is lost (`HubLost`), `via_service` never sets `told` (`src/sheafmd/lifecycle.py:149-150`), so a later manager failure does not take the announcement back.
- [ ] **A cancelled Tell delivery that cannot be killed is not counted as busy.** With no stop job started, it is not counted by `Hub.busy()` (`src/sheafmd/hub/core.py:1339-1346`), so a non-forced upgrade stop can proceed over it. Unproven: reproduce first.
- [ ] **A newer command meeting a plain stop already under way.** `request_stop("upgrade")` returns True and leaves reason `stop` (`src/sheafmd/hub/core.py:1307-1314`); the hub exits 0, the service does not restart it, and `_meet_version` reports "the hub did not come back on the new version" (`src/sheafmd/hub/client.py:418`). Decide what the command should say or do.
- [ ] **`on_stop` is called outside `_stop_lock`.** `Hub.request_stop` calls `on_stop` after leaving the lock (`src/sheafmd/hub/core.py:1323-1324`), so two callbacks can arrive in the opposite order of their decisions. Harmless today; document it or call it under the lock.
- [ ] **A nested signal during a stop has not been reviewed.** The SIGTERM handler runs `request_stop` (holding `admit` and `_stop_lock`, both re-entrant) on the main thread; what a nested signal can reach through `on_stop`/`announce_stop` is unreviewed.

## HTTP

- [ ] **`Accept` is matched as a substring** (`src/sheafmd/hub/handler.py:320`): `text/html;q=0` counts as asking for HTML, and case matters. Parse it as a media-type list.

## Refactors left on purpose

- [ ] `cli.cmd_stop` (`src/sheafmd/cli.py:383-420`) duplicates `hubclient.stop_and_wait` (`src/sheafmd/hub/client.py:381`): add characterization tests for its two messages, switch it over, delete `cli._ended` (`cli.py:378`).
- [ ] `src/sheafmd/lifecycle.py:23-41` copies `EXIT_*`, `_out`, `_err`, `_parser`, `_hub_failure` from `cli.py`.
- [ ] `service.kind() == "systemd"` is decided five times in `src/sheafmd/hub/service.py` (`:194`, `:202`, `:231`, `:301`, `:315`) and the "user service is for Linux and macOS" sentence is written twice (`:244`, `:295`): a per-platform object.
- [ ] `(c, got)` travel together through `stop_and_wait`, `_meet_version`, `via_service`, `cmd_restart`, `cmd_rotate`; `via_service` and `service.control` take bare verb strings.
- [ ] `run_hub`/`wait_alive` exist twice: `tests/test_cli_hub.py:437-442` and `tests/test_hub_lifecycle.py:22-35`.

## macOS tests

- [ ] Hub tests that set `XDG_RUNTIME_DIR` share the real `/tmp/sheaf-<uid>` on macOS, because `paths.runtime_dir` (`src/sheafmd/paths.py:71-77`) ignores it on darwin by design; add a test-only short-path override. The restart tests of `tests/test_service.py` with the fake `systemctl` have never passed on macOS (no green macOS run on main, see tickets 96 and 101).

## Lint and names

- [ ] `ruff check` flags `src/sheafmd/cli.py:37` (unused import `url_path`) and `tests/test_hub_rotate.py:135` (unused `hub`).
- [ ] The ticket's last box (no real first names and no private host names in `src`, `tests`, `tools`) fails on main: a real first name appears in 18 test files and a private host name in 7. Carried in full by ticket 155.
