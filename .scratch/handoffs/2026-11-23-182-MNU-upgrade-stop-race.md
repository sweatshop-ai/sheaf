# Handoff: ticket 182 M, N, U (client upgrade-stop race from #508)

**Owner:** Arvid, track sheaf-backlog, 2026-11-23
**PR:** sweatshop-ai/sheaf#606, branch `arvid/182-upgrade-stop-race`, head f8c388e0
**Status:** review GO (Matt code-review GO; fallback round 1 GO on 7bd48efd; fix-pass round 2 GO on f8c388e0, Opus, provisional: Codex at its limit until 07:15Z, so Codex re-reviews before any release)

## What the PR does

- **M and N** (`src/sheafmd/hub/client.py`): after the old hub has ended, the command reads that hub's exit row (`exit_reason`, the `hub-exit` row for its `boot`, waiting up to `EXIT_ROW_WAIT` = 2 s). It then decides:
  - a row that says `stop`: no hub is started and no wait for one; the command fails with "the hub is being stopped";
  - a row that says `signal`, without the service: the same;
  - a row that says `signal`, under the service: the command waits for the hub the unit starts again (14.3);
  - a hub that left no row (killed): it is replaced, as before.
- **U** (`src/sheafmd/hub/server.py` `HubServer.stop`): `hub-stopping` carries `hub.stop_requested`, not the reason of the callback that arrived first.
- SPEC 8.4 says both. It also says that a stop decided after `hub-stopping` has gone out cannot be told, because that event is the stream's last.

## Tests

The tests are in `tests/test_hub_upgrade.py`:
- Red first on ba3bffa6: the M test (stop, signal), the N test (stop and signal without the service, stop under it) and the U test.
- Controls: an `upgrade` row starts the new hub; a stray signal under the service waits for the restarted hub.
- Local: test_hub_upgrade, test_hub_server, test_client_*, test_spec_page_pins, all green.

## Review findings not acted on

- **Exit row too late when no pid is known** (raised in rounds 1 and 2): rejected. `HubServer.stop` runs `stop_jobs()` (job grace, then the pull and push of `commits.stop`) before `httpd.shutdown()` closes the port. The second `stop_jobs` in `close()` returns at once. So the row follows the silence by milliseconds, not seconds.
- **A killed hub costs 2 s more per upgrade:** accepted. It is rare, and the cost is bounded.
- **Two minor follow-ups,** listed in ticket 182 under "Follow-ups from PR 606":
  - `ask_stop` (`client.py:403-404`) still fails at once under the service when the hub's answer is `signal`;
  - a `signal` row cannot tell a stray SIGTERM from a `systemctl stop`.

## Next

Merge #606 once CI is green on the head (main deploys nothing). Then tick nothing more: M, N and U are ticked in the PR.
