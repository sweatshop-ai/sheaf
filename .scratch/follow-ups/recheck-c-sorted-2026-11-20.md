# Recheck of minor findings, kind (c): sorted against main 38db64d2, 20 November 2026

Each of the 78 kind (c) items in `opus-recheck-triage-2026-11-20.tsv` was read against the code on main and sorted into one group. The number before each entry is the line in `opus-recheck-minor-findings-2026-11-20.md`.

## Counts

- Fixes: plainly a defect: 14
- Behaviour decisions for the owner: 43
- Not a defect: 19
- Already fixed on main: 1
- Unknown: needs a run: 1

Two earlier triage notes were wrong and are corrected below: 273 (the lock order is the one `wake` already uses, so it is a plain fix) and 439 (SPEC already says 403; the hub has no check, so it is a code fix).

## Proposed pull requests for the fixes

Each fits one 150k session. Red test first in every one.

1. **Trust boundary: the two visibility checks agree (hub-core, small)**: items 67 and 123. `may_open` also requires `member_owns`; `shared_with` applies the private-source rule `opened_by_line` already applies. Needs a regression test for each and a `security-review` run before merge.
2. **Hub: one read of the file for the visibility judgement (hub-core, medium)**: items 121 and 122. `may_open` takes the locked text and forwards it to `opened_by_line`; the audience and sources are cached in the `_front` entry on the same stat key. Behaviour does not change.
3. **Shared live stream (hub-handler and page-js, small)**: items 373, 424 and 376. A join on a closed stream answers 404; a late join on an old stream never takes the key from a newer one; the Leader constructor stops opening the stream at once. The page change is checked by the shared-live browser tests in CI on the CI runner host, not on the laptop.
4. **Generated page is read-only through the hub (hub-handler, medium, with the spec)**: items 439 and 437. One check on the `docs` entry's `generated` mark in `_save`, tick and `_share`, answering 403 as SPEC.md:684 already says; SPEC.md:945 and :1678 state that a key caller's mark has no token as setter.
5. **Small leftovers (three areas, all small)**: items 273 (`sleep_moved` takes `holding(dest)` before `_records`), 306 (an unbound token that may see a sleeping clone page gets the asleep line, per SPEC 8.7) and 411 (`_without_placeholder_breaks` and `_cell_breaks` see one fragment).
6. **Tests only (small)**: items 339 and 346 (slow the carry instead of `versions.put`; widen `EXEC_WINDOW` in the leakguard test). Can ride with any other PR if the queue is short.


## Fixes: plainly a defect

### 67 (PR 394)

area hub-core, size S (trust-boundary code: needs a regression test, run security-review on it).
Claim true: may_open (hub/core.py:1344-1353) passes any member on a loose page whose fm keeps `visibility: project` (names_only is skipped for loose roots, hub/handler.py:1698-1700), while the pre-lock gate `_owned` also requires `member_owns`, which asks `shared_with` (hub/handler.py:719-720, hub/core.py:1176,1181). Fix: make may_open also require `self.member_owns(member, address)` (or shared_with for a loose root) so both checks judge the same predicate. No product choice: the gate already defines it.

### 121 (PR 403)

area hub-core with hub-handler/the_list callers, size M.
Claim true on main: may_open (hub/core.py:1344-1353) calls opened_by_line(member, address) with text=None, which re-reads the file (core.py:1389-1395), not the locked text its `fm` came from. Note "six callers" is stale: opened_by_line has three callers (core.py:1342, 1351, 1375); may_open has six call sites (handler.py:1456,1661,1813,2120,2205; the_list.py:982). Fix: add an optional `text` parameter to may_open, forward it to opened_by_line, pass the locked text from the callers that hold it.

### 122 (PR 403)

area hub-core, size M.
Claim true: visible() (hub/core.py:1342) calls opened_by_line(member, address), which opens and reads the file each time (core.py:1389-1396), while judged() (core.py:1275-1301) keeps `_front` keyed on (ino, mtime, ctime, size). Fix: store the audience (visibility.audience(text)) and UNREAD/sources facts in the same _front entry, keyed on the same stat key, and have opened_by_line read from it when text is None. Pure cache, no behaviour change.

### 123 (PR 403)

Area hub-core, size S. `shared_with` (core.py:1181-1192) judges a loose page by `visibility.reaches(self.audience(address), member)` and never applies the private-source rule. Its sibling `opened_by_line` does (core.py:1396-1397: a page drawing on a private source opens only through the owner's own `shared`). A hand-ticked Share on a page with a private source therefore opens it through `members_owning` (core.py:1176). Fix: apply the same check (read the text once, `any(visibility.private(x) for x in visibility.sources(fm)) and not visibility.text(fm, "shared")` returns False) inside `shared_with`. No new rule: it makes the two paths agree.

### 273 (PR 438)

Area: hub-core (repos.py), size S. Claim true: repos.py:278-284 updates a sleeping row under `_records` only, while `wake` holds `self.holding(dest)` first (repos.py:408) then `_records`. Taking `holding(dest)` before `_records` in sleep_moved is the same order `wake` and `_sleep_one` (repos.py:346-347) already use, so the note's lock-order worry does not hold. `sleep_moved` has no caller in src today (only tests/test_moved_clone.py), so wire the lock in before it gets one.

### 306 (PR 444)

Area: mcp-door, size S. SPEC section 8.6 text for a sleeping clone says a door call by a token that may see the page is answered with the asleep line. mcp.py:477 returns None for every unbound token (member None), though `_sees` can judge it from the last read front matter (mcp.py:570-572: visibility project, not private) and `self.hub.judged(address)` is already known non-None at mcp.py:476. Fix: for member None, return None only when `not self._sees(judged[0], address, caller)`; add a door test for an unbound token on a sleeping clone page.

### 339 (PR 452)

Area tests, size S. The failure point is `versions.put` slow, so `_in_time` (src/sheafmd/hub/incoming.py:140) raises before `hub.writes.carry` (:143) adds a line, and `undo` returns early (writelog.py:248-249). Fix: slow `hub.writes.carry` (add the other writer's line, then sleep past the deadline) instead of `versions.put`, so the failure comes at :145 after the carry. Evidence: tests/test_peer_transfer.py:374-392.

### 346 (PR 453)

Area tests, size S. `_after_exec` (tests/leakguard.py:75-81) loops only while `_is_executing` (age under EXEC_WINDOW), so a stalled runner returns None. Fix: in the test `monkeypatch.setattr(leakguard, "EXEC_WINDOW", 60)` (or patch `_is_executing` to True); the test is then deterministic. Evidence: tests/test_leakguard.py:246-255.

### 373 (PR 474)

Area hub-handler, size S. `Shared.join` returns silently when `closed` (src/sheafmd/hub/events.py:143-146) and `_live_join` then answers 200 (src/sheafmd/hub/handler.py:915-925); `_shared_of` already answers 404 for a closed stream (handler.py:903-905) and the page turns a non-2xx join into a `refused` event (src/sheafmd/page/live.js:185-190). Fix: `join` returns False when closed, handler raises `Refuse(404, "no such stream")`.

### 376 (PR 474)

Area page-js, size S. The Leader constructor calls `this.connect()` at once (src/sheafmd/page/live.js:134), although `take` already opens the stream lazily on the first join (live.js:199-201) and `stop` copes with `es === null` (live.js:144). Fix: drop the constructor's `connect()`. Needs the shared-live browser tests on CI (not the laptop).

### 411 (PR 482)

Area other (src/sheafmd/edit.py), size S. `_without_placeholder_breaks` computes `table_is_taken` from the raw fragment (edit.py:593), while `_cell_breaks` tests `"\\" in fragment` after `_text_backslashes` (edit.py:787-789, :655). Fix: compute `table_is_taken` on `_text_backslashes(fragment)[0]` (or run `_text_backslashes` before `_without_placeholder_breaks`) so both see one fragment; add a test with a cell `a\\*` and Enter's break.

### 424 (PR 484)

Area hub-handler, size S. A late join on an old stream runs the `others` leave loop (src/sheafmd/hub/handler.py:915-922) and drops the key from the newer stream. Fix: give `_SharedStream` a creation order (set in `_shared_stream`, handler.py:884-896) and leave the key only from streams older than the one joined, so an old stream's late join never takes the key from a newer one.

### 437 (PR 486)

Area docs/spec, size S. The code already fixes the rule: a key caller's mark is `{"by": display, "id": None, "at", "key": True}`, no token is its setter and only the key may change or clear it (src/sheafmd/mcp.py:944-949, :930-932). Fix: state that in SPEC.md:945 and :1678 (the feature is not spec-only: mcp.py:132, :145, :911).

### 439 (PR 486)

Area hub-handler, size M. SPEC.md:684 and 7.2 (SPEC.md:499) now say `/_/share`, `/_/save` and `/_/tick` answer 403 "Generated by <token name>. Edits are not kept; comment instead." for a generated page, but nothing in src/sheafmd/hub/ reads the mark (grep `generated` finds only src/sheafmd/mcp.py and edit.py; `_share` at src/sheafmd/hub/handler.py:1434-1445 has no check). Fix: one check, built on the `docs` entry's `generated` key as `mcp._mark` reads it, in `_save`, tick and `_share`, with tests.


## Behaviour decisions for the owner

### 12 (PR 385)

Still true: hub/core.py:999 `self._refreshed(e)` sits in render() with no try; the tick paths wrap it (core.py:1590-1600 via _rebuild_failed). Options:
- A (recommended): wrap at core.py:999 like the ticks, log via _rebuild_failed, render still returns OK, so a file that fails to render does not fail a render call.
- B: let it raise (current), so the caller sees the render failure.
- C: A plus merge the refresh `changed` and the settings rebuild into one event.
Evidence: hub/core.py:999-1003, 1597, 1678-1686; hub/live.py:621-643.

### 36 (PR 388)

Still true: connect.py:249-250 reads ~/.claude.json, then write_text_atomic with no lock; Claude Code takes none. Options:
- A (recommended): re-read and compare mtime/size just before the replace, retry once on change, then refuse with a message.
- B: advisory lock file next to it (Claude Code will not honour it, so protection is partial).
- C: leave, document that connect should be run with Claude Code idle.
Evidence: src/sheafmd/connect.py:224-250.

### 37 (PR 388)

Still true: connect.py:212-214 `r.read(1 << 20)` under per-operation TIMEOUT; keep-alives hold it. Options:
- A (recommended): overall deadline (e.g. monotonic cap of 2x TIMEOUT) around the read, read in chunks and stop at the first complete `data:` line.
- B: only read to the first `data:` line, no deadline.
- C: leave.
Evidence: src/sheafmd/connect.py:205-216.

### 38 (PR 388)

Still true: hub/laptops.py:34 `of()` filters `not r.invalid`; revoke() (laptops.py:59-65) selects from of(). Options:
- A (recommended): revoke() looks at all the member's laptop rows including invalid; the listing still hides them (or marks them).
- B: list invalid rows with a flag in /_/laptops so they are visible and revocable.
- C: leave; `sheaf token revoke` on the hub ends it.
Evidence: src/sheafmd/hub/laptops.py:33-65, hub/handler.py:2063-2090.

### 51 (PR 390)

Still true: page/sheaf.js:83 window.open in the rejection handler after the async ask() (sheaf.js:57-60), no timeout. Options:
- A (recommended): AbortController timeout on ask() of about 1.5 s, so rejection comes while activation is alive.
- B: open the Remote Control tab synchronously in the click and navigate it after the answer.
- C: leave; the fallback only matters when AgentView hangs.
Evidence: src/sheafmd/page/sheaf.js:57-60, 72-90.

### 74 (PR 395)

Still true: page/page.js:2436 filter drops `t.target === targetNow()`. Options:
- A (recommended): keep the exclusion (a Tell already aimed at that agent has nothing to move to), and show a line "your only agent is the laptop this Tell waits for".
- B: drop the exclusion when the Tell is waiting for a laptop session, so Retarget to the same agent becomes a re-queue.
- C: leave.
Evidence: src/sheafmd/page/page.js:2435-2443.

### 75 (PR 395)

Still true: hub/handler.py:2420-2424 targets.restore runs after the `_reading` block ends at 2419. Options:
- A (recommended): restore only if the stored target still equals the one this call picked (compare-and-restore), no lock-order change.
- B: take `_reading` again around restore.
- C: move start_member_tell inside `_reading` (touches lock order with the tell machinery).
Evidence: src/sheafmd/hub/handler.py:2400-2426.

### 79 (PR 396)

Still true: connect.py:208-209 entry_name maps `https://[::1]:8443` to `sheaf---1-8443`. Options:
- A (recommended): leave; valid name, rare input, renaming orphans existing entries in users' ~/.claude.json.
- B: new readable form for IPv6 only, and add_mcp_entry also removes the old-form entry.
- C: new form for all, with a migration.
Evidence: src/sheafmd/connect.py:208-209; tells_poll.py:62 relies on entry_name matching.

### 83 (PR 397)

Still true: send.py:358-363 uses `md.resolve().parent` for load_root_config, not the registered root. Options:
- A (recommended): walk up from the file to the nearest `.sheaf.toml` (stop at git/home), no hub call.
- B: ask the hub/roots registry for the file's root.
- C: keep file's own folder and fix SPEC 13 wording to say so.
Evidence: src/sheafmd/send.py:355-364.

### 86 (PR 397)

Still true: send.py:386 write_text_atomic(beside, ...) overwrites FILE.tiroir.md. Options:
- A (recommended): overwrite only when the existing file equals the last tiroir text recorded in the row; otherwise number it (FILE.tiroir.2.md) and name that in the error.
- B: refuse with a message to merge or delete the existing one first.
- C: leave overwrite (it is a copy of the tiroir's text).
Evidence: src/sheafmd/send.py:380-392.

### 101 (PR 400)

Still true: hub/repos.py:224-228 _read returns {} on ValueError; _write (repos.py:230-232) then replaces the file. Options:
- A (recommended): on a corrupt file rename it to reports.json.corrupt-<stamp>, log once, then start empty.
- B: refuse (raise) until a human fixes it, so no render report is recorded.
- C: leave.
Evidence: src/sheafmd/hub/repos.py:224-232.

### 103 (PR 400)

The unlocked write is harmless (single dict set under the GIL, repos.py:493-495, worst case two ssh -G calls). The never-expiring cache is real. Options:
- A (withdrawn, ticket 190 H): key the cache on ~/.ssh/config mtime. It misses `Include` files and the system config, which `ssh -G` reads too, so a stale name stays.
- B (recommended): TTL of 5 minutes.
- C: leave; restart picks it up.
Evidence: src/sheafmd/hub/repos.py:200, 493-495.

### 108 (PR 401)

Still true: tells_poll.py:48-52 reads only top-level mcpServers. Options:
- A (recommended): leave; it fails closed and sheaf connect writes user scope, so project-scope entries are not the ones the mod should trust.
- B: also read the project block of ~/.claude.json for the cwd.
- C: also read .mcp.json (widens what the mod trusts; needs the same entry_name check).
Evidence: src/sheafmd/tells_poll.py:46-60.

### 115 (PR 402)

Still true: register.ts:177-182 session.start calls restore(m.p, sent, ...) before checking p.armedFor. Options:
- A (withdrawn, ticket 190 G): skip restore when m.p.armedFor is non-empty and differs from id. It leaves the resumed session unarmed: session.start arms only while p.doors is empty, and leave() clears state without arming again, so Tell polling stops until another declaration.
- B (recommended): call leave(m) first when armedFor differs, then restore and arm.
- C: leave; the effect is a possible repeat Tell, the accepted direction.
Evidence: plugin/sheaf/hooks/register.ts:176-185, core.ts:105-115.

### 116 (PR 402)

Still true: register.ts:75-76 undo = putBack(p,t) runs on `drop` after the Tell's turn started; putBack (core.ts:142-147) removes it from delivered but p.stored and the store keep it. Options:
- A (recommended): on putBack also remove the id from p.stored and rewrite the kept set, so memory and store agree with "resubmitted".
- B: do not putBack once turn.start recorded it (a dropped Tell at turn end is not resubmitted).
- C: leave.
Evidence: plugin/sheaf/hooks/register.ts:68-76, core.ts:142-147.

### 133 (PR 405)

`_folder` (moves.py:52-57) goes through `loose.folder_path`, which refuses an empty part (loose.py:49), so "" (the root top) is refused. Claim true.
- A: keep refusing; a loose page always lives in a folder (RECOMMENDED: the month default, loose.py:44-45, and `_put`'s `f"{folder}/{name}"` at moves.py:105 assume it).
- B: accept "" as the root top in move_page only (needs `new_rel` built without the slash and the folder-move rule changed).
- C: accept "" only for single pages, not folders.

### 137 (PR 405)

`forget_root` (core.py:1022-1026) takes only `self._lock`; `_undo` ends with `hub.forwards.restore(before)` (moves.py:236), which clears and rewrites all Forwards from a snapshot taken at moves.py:206, so a forget in between is undone for its Forwards. Claim true. The lock fix is unsafe: `loose.drop` holds the loose lock and the `loose.lock` file lock, then calls `forget_root` (loose.py:300-306), while moves take `_LOCK` then read the loose registry (moves.py:190-192), so adding `moves._LOCK` to `forget_root` creates an inversion.
- A: `_undo` restores only Forwards of roots still registered (no new lock) (RECOMMENDED).
- B: take `moves._LOCK` in the handler's forget route only (handler.py:2563), not in `loose.drop`.
- C: leave; needs a failed folder move racing a forget.

### 142 (PR 406)

Claim true: repos.py:710 answers `commit_known` as `self._look_is_safe() and ...`, so on git below 2.44 it is False for every ok report, and send.py:555-557 prints "is it pushed to GitHub?". send.py:313-314 rejects an ok with a None `commit_known`, so None needs a protocol change; the hub logs once at repos.py:215-218.
- A: reword the CLI line to also name an old git on the tiroir ("or the tiroir's git is older than 2.44"), no protocol change (RECOMMENDED).
- B: allow None for ok in send.py:313 and incoming.py:279 and word it "cannot tell".
- C: leave; the hub log already says it.

### 146 (PR 407)

Claim true: `root_config` (commits.py:326-332) forces commit and push for any root with `clone` set, while `Hub.clone_of` (core.py:374-377) returns "" when `_repos` is None, so such a root commits and pushes with no repos service.
- A: `root_config` honours `clone` only when the hub has repos; else read the root's `.sheaf.toml` (RECOMMENDED; matches clone_of and `members_owning` core.py:1174).
- B: refuse to register or serve a root with `clone` when repos is off.
- C: leave.

### 147 (PR 407)

Claim true: `decide` (repos.py:558-583) without a token reads `origin/HEAD:.sheaf.toml` with `look=True`; when the look is blocked or fails, `named` is None and the "add branch = ..." line is stored in `_saves` (repos.py:581), so a clone stays read-only with a wrong reason until the next decide with a token (repos.py:654).
- A: do not store the result of a tokenless decision whose look failed (RECOMMENDED).
- B: store it but marked provisional, redecided at the next report.
- C: leave; it fails safe.

### 150 (PR 407)

Claim true: proxy.py:467-475 builds `named` from `(m.short or m.id)` per member, so one member's `short` colliding with another member's id (who has a `short`) is not caught. SPEC.md:997 says the owner name belongs to one member "against every other short and id".
- A: check each member's short and id against every other member's short and id, as the spec says, and fail the start with a message naming both (RECOMMENDED; the spec is the contract and a collision lets two members share an owner key).
- B: change the spec to the code's rule.
- C: warn at start instead of refusing, for configs already running.

### 159 (PR 408)

Claim true: `marks_of` (sheaf_view.py:204-208) reads the owner's marks for a shared row too, and `archived`/`kept` (sheaf_view.py:229) then place the row in the recipient's Archived view (sheaf_view.py:249).
- A: shared rows are never archived or kept for the recipient (the marks are the owner's housekeeping) (RECOMMENDED).
- B: keep as is; the owner's Archive is the recipient's too.
- C: per-member archive marks for shared pages (new store).

### 160 (PR 408)

Claim true: `SEEN` and `ARCHIVED` entries are removed only in `trash` (archive.py:217-218) and carried on a move (core.py:1071); a page deleted or moved outside the hub leaves its entries forever. The sweep (archive.py:146-150) only adds.
- A: in the sweep, drop entries whose file is absent, only when the listing was complete (no cap, no read error) (RECOMMENDED).
- B: drop entries absent for more than N days.
- C: leave; the entries are tiny.

### 172 (PR 410)

Claim true: `TeamComments` is keyed by address (team.py:27-50), and `moved_page` (core.py:1065-1071) carries every store except `team`, which is not in the list; no read follows Forwards. A moved page loses its team comments from view.
- A: add `team.rename(old, new)` to the `moved_page` steps (RECOMMENDED; same pattern as the other stores, and the Forward is already written).
- B: follow Forwards on read.
- C: leave.

### 176 (PR 411)

Claim true in part: `_land_steps` rollback (incoming.py:150-163) unlinks the file, forgets versions, undoes Write log lines (writelog.py:243) and un-keeps/un-archives, but not the `door._create` side effects: the hub's wrote/committed record, a git commit in a git root, and loose folders it made. A loose root is not a git root in the common case, so the commit part is rare.
- A: undo the wrote record and remove folders the landing made when empty; do not rewrite git history (RECOMMENDED).
- B: undo everything including a revert commit in a git root.
- C: leave.

### 178 (PR 411)

Claim true: transfers.json is keyed by `b["id"]` alone (incoming.py:97, 150); the id is any sender text up to 64 characters (incoming.py:62). Two peers using one id get the first one's answer.
- A: key by (peer origin, id), a local caller keyed by "" and old entries read as before (RECOMMENDED).
- B: require ids to be random (uuid) and reject others.
- C: leave.

### 180 (PR 411)

Claim true: `carry` (writelog.py:158, via incoming.py:144-146) writes the transfer line with the bundle's `by`, only `clean()`ed, so a paired tiroir names the writer of the log line.
- A: writer is the owner's name; the sender's `by` goes into the line's host/place together with the authenticated peer origin (RECOMMENDED).
- B: keep `by` but prefix the peer origin.
- C: leave.

### 187 (PR 412)

Claim true: `restore_trash` uses `os.link` (archive.py:261) and answers with a `loose.Refused` message on OSError (archive.py:264-265); on a filesystem without hard links the restore fails every time. The link is what stops a concurrent create from being overwritten (archive.py:254-256).
- A: keep; the hub's data folder is a normal Linux filesystem, say in SPEC that hard links are required (RECOMMENDED).
- B: fall back to renameat2(RENAME_NOREPLACE) where available.
- C: fall back to copy plus fsync under the file lock.

### 192 (PR 415)

Claim true: `adopt` (readthrough.py:56-57) keeps the `rd-edit-meta` JSON block of a client page verbatim. It is data, not script, but the agency page's script reads it.
- A: filter it to the keys the page script reads, drop the rest. Withdrawn (ticket 190 F): the keys the script reads (`doc`, `actions`, `edit`, the agent) are the ones a client hub can forge.
- B: keep; the client tiroirs are the agency's own and the block is read as JSON only.
- C: replace the block with one the agency hub builds. Done in ticket 190 F for what the script acts on: the agency sets `doc` and empties actions, editor and agent.

### 214 (PR 422)

Claim true: sender's `timeout=seconds or channel.SECONDS` (outgoing.py:59) is per socket operation; the receiver's deadline is `req.arrived + channel.SECONDS` (handler.py:598). Both are 60 s from about the same moment, so the sender can give up as the landing finishes.
Options: (a) shorten the receiver's deadline by a margin (e.g. arrived + SECONDS - 5) so it finishes before the sender stops waiting (recommended, S); (b) make the sender's wait a true total deadline (design change); (c) leave: the kept outgoing id makes a plain resend land once, worst case is a name_taken refusal and two copies, no loss.

### 222 (PR 425)

Claim true: archive.py:142 lists pages outside any lock; archive.py:143-149 stamps under `loose-keep.lock` only, while every handler act takes `moves._LOCK` first (handler.py:1513).
Options: (a) after taking `moves._LOCK` then `loose-keep.lock` (order moves before file locks, lockorder.py:6 allows it), drop from the stamp any rel no longer in the page list, re-checked by stat (recommended, S-M); (b) hold `moves._LOCK` across the listing too (blocks every move for the slow listing); (c) leave: the stale mark is harmless for a path that no longer exists.

### 237 (PR 428)

Claim true: repos.py:728 (`refusal`) and repos.py:701 (`report`) each call `provider.token` (a subprocess, up to 30 s, repos.py:839) for a repo with no clone.
Options: (a) leave: it is the first-report path only, once per clone (recommended); (b) a short-lived per-repo token cache in CommandProvider (a token held in memory, a security choice); (c) `refusal` returns the token it fetched for `report` to reuse (changes both signatures).

### 259 (PR 434)

Claim true: page.js:1219 sends `branch: CFG.branch`; handler.py:1257-1262 `_read_on` answers 400 when a clone page sends none. Edits are kept to copy, not lost.
Options: (a) accept: the mount's upgrade path (mount.js:437-446) already tells the old page to reload, the window is one hub upgrade (recommended); (b) the hub treats a missing branch as "unknown" for one release (weakens the guard); (c) page-side migration of old drafts (L, for a one-time case).

### 272 (PR 438)

Claim true: repos.py:413 `_use` writes clones.json on every wake (repos.py:247-254). The sleep threshold is `SLEEP_DAYS = 30` (repos.py:65).
Options: (a) skip the write when the clone is awake and last_used is under an hour old, costing at most an hour of 30 days of accuracy (recommended, S); (b) leave; (c) batch the date in memory and flush on the tick.

### 286 (PR 440)

Claim true: connect.py:82 maps every character outside [A-Za-z0-9._-] to "-", so `a.example:8443` and `a.example-8443` share a file name; the token for one would be sent to the other.
Options: (a) leave: both would have to be peers of one owner, contrived. Withdrawn (ticket 190 E): it sends one peer's token to another, so it was fixed with a name no two origins share; (b) encode ':' as '_' and read the old name as a fallback in `_credential_file` (connect.py:93-98), M; (c) keep the name and refuse to store when two origins collide.

### 297 (PR 442)

Claim true: sheaf.js:583 writes a refusal through `say()` (sheaf.js:355), the one shared line.
Options: (a) prefix the message with the folder or page name the form belongs to (recommended, S); (b) a status element inside each form (M, css too); (c) leave.

### 322 (PR 448)

Claim true: tests/test_clone_sleep.py:137 `helper[0].join(0.5)`; on a loaded runner the old code can pass; no false failure on the fixed code.
Options: (a) leave: the fix is covered at the source, the test only loses sharpness under load (recommended); (b) raise to 2 s (slows the fixed path by the same amount, since the helper blocks on the guard); (c) instrument `repos._guard` with a wrapper that sets an Event on an acquire attempt and wait on that (M, test-only).

### 327 (PR 449)

Claim true: page.js:3082 `if (teamBusy) return;` runs before Reply, Edit and Cancel, which are local form actions (page.js:3088-3089), so they drop silently while a write is out.
Options: (a) move the guard to after the local acts, so only network sends (delete confirm, status, send) are blocked (recommended, S); (b) keep the guard and show a "wait for the write" line via `say`; (c) leave.

### 334 (PR 450)

Claim true: `leaving` reads `window.__leaving`, set only by a `beforeunload` already fired (tests/page/pagehelp.py:553-571), so a reload that starts after the check is invisible.
- A: accept, it is a limit of seeing a navigation from the page (recommended)
- B: each test that can trigger a late reload waits on its cause (the `changed` event) before the teardown
- C: a hub or page debug counter of reloads scheduled, read by the teardown

### 362 (PR 457)

Claim true: src/sheafmd/page/sheaf.js:435 `if (gone || lpanel.hidden) return;` drops the answer, and `laptopsClose` (sheaf.js:378-381) hides `lmade`, so the one-time command is lost while the laptop exists (it shows in the list on reopen and can be revoked).
- A: leave; closing discards the one-time command, the row can be revoked and made again
- B: set `lline`/`lmade` on the answer even when the panel is hidden, so reopening shows the command once (recommended)
- C: on an answer after close, revoke the new laptop automatically

### 390 (PR 477)

Claim true: `_drawn_actions` drops a line when `check` holds but `box_number` is None (src/sheafmd/hub/the_list.py:367-373); None also means "empty item", so a render failure cannot be told from a non-box and changes what counts as an action and the save guard.
- A: leave; transient, one poll (recommended only if the flipped render never fails in practice)
- B: `box_number` signals render failure apart from "not a box" (not cached) and the block falls back to line reading for that read
- C: a failed flipped render fails the whole read

### 423 (PR 484)

Claim true: `resume` fails every open source and re-asks (src/sheafmd/page/live.js:253-258); the hub replaces the key (src/sheafmd/hub/events.py:139-146), so the result is correct but pages see an error/open cycle.
- A: accept; correct result, a documented freeze protocol (recommended)
- B: on resume, fail and rejoin only after a `who` shows the leader changed, otherwise rejoin quietly
- C: the leader confirms membership per key and the tab fails only the keys it lost

### 428 (PR 485)

Claim true: SPEC.md:1694 says every CLI output is free of any tiroir mention, while src/sheafmd/connect.py:291 ("has a `tiroir` entry"), src/sheafmd/send.py:613 and the `tiroir =` key (SPEC.md:239) say it.
- A: narrow the rule to the product and vendor name, with the `tiroir` config key and messages that name it as exceptions (recommended)
- B: reword the messages (for example "server entry") and keep the key
- C: rename the key (breaking for existing `.sheaf.toml` files)


## Not a defect

### 110 (PR 401)

Tell ids are unique and p.delivered is process memory only (plugin/sheaf/hooks/core.ts:34,111,134,143); growth is one string per Tell. leave() (register.ts:35-44) clears what must be per-id; clearing delivered would risk a repeat Tell across /clear, against the documented "errs toward repeat" direction in the other.

### 117 (PR 402)

By design and documented: a turn.start whose text does not contain t.message is treated as the member's typing (register.ts:196-199 comment "not the member's own typing"); the Tell errs toward a repeat (register.ts:47-52), never a loss, and the next empty-text turn records it.

### 185 (PR 412)

handler.py:344-347 deliberately answers 404 "no such document" when the file is gone (`_page_gone`, handler.py:357-362): this is the expected race of a writer that waited for a Delete's lock, as the inline comment says; recording an exception there would fill diagnostics with a normal outcome. Other FileNotFoundError cases still reach `_failed` (handler.py:349).

### 193 (PR 415)

By design and fail-closed: readthrough.py:48-61 keeps only the script byte-identical to this hub's `page_script()` and drops every other script, so a client on another build renders without script instead of running code the agency did not vouch for; the module docstring (readthrough.py:43-46) states this.

### 197 (PR 416)

`check_root` and `send_root` answer different messages: `check_root` (incoming.py:239, 284) is the pre-flight whose answer is `{"ready": True}` and is asserted so by tests/test_land_root.py:85; `send_root` (outgoing.py:271) reads the answer of the landing verb `root`, which says `ok`. No caller of `check_root` exists yet, and the future caller reads `ready`.

### 207 (PR 417)

`is_ending` (tests/leakguard.py:136-148) returns the right answer for an unreadable environment (False after the window); the only effect is a wait of at most `EXEC_WINDOW` = 1.0 s (leakguard.py:32). Its callers pass processes carrying this run's mark, so their environment is readable (tests/conftest.py:332, tests/test_real_hub_untouched.py:87-89).

### 260 (PR 434)

A replay writes nothing (live.py:250-252, answers the earlier result) and the earlier save landed on the branch it was read on; the `again` answer is accurate, and the next save is refused by the guard at handler.py:1294. Nothing is hidden that matters.

### 271 (PR 438)

repos.py:416 runs only when the clone is asleep (the early return at repos.py:413-414 skips it otherwise), and the restore that follows needs the same commit lock and the token (repos.py:417); no save, pull or commit of that repo can do anything useful before the restore ends, so fetching the token earlier would only move the same wait.

### 280 (PR 439)

writelog.py:263 `restore` appends a retraction marker plus the kept lines in one write by design (file append-only, writelog.py:260-262); growth is bounded by KEEP = 200 (writelog.py:18) and rotation at MAX_BYTES (writelog.py:19, :170), lossless.

### 287 (PR 440)

connect.py:121 ("made 0700 if it is not there") is the documented contract of `use_peer_file`, the token file itself is 0600 (connect.py:135, :137 fchmod); chmod-ing a folder the user named would change a directory the tool does not own.

### 301 (PR 443)

connect.py:134-135: only an asynchronous KeyboardInterrupt between two bytecodes can land there; setting `made` before `os.open` would unlink a foreign leftover link the code means to leave (comment at connect.py:127), and the `except BaseException` branch (connect.py:148-) already cleans the normal cases. No code closes the window fully.

### 312 (PR 445)

Documented as intended at tests/public_tree.py:21-23; it applies only to the guard's own two files (`OWN_FILES`, public_tree.py:122), which hold the planted addresses; narrowing would only make the guard's fixtures fail.

### 316 (PR 446)

Every stale path has an owner that unmounts `page`: handle.unmount (mount.js:462-464), the next draw (`if (page) page.unmount()`, mount.js:437), the overtaking mount (`pane.live.unmount()`, mount.js:411). The window in which the kit is live is the same one any remount has before its own fetch lands.

### 333 (PR 450)

Hypothetical by the finding's own words: the `tab` fixture is for sheaf pages, whose menu `#rd-menu-btn` the teardown waits for on purpose (tests/page/pagehelp.py:570-575, tests/page/conftest.py:183); a test leaving for a non-sheaf page would use `landed_page`/`close_context`, and none does.

### 357 (PR 455)

By design and harmless: `_watch_drops` expires drops against the file first (src/sheafmd/hub/core.py:1523-1529), and a drop whose reply is already in the file is over and the reply clears the line, so there is nothing for an `answered` state to move.

### 406 (PR 481)

`**`c`**` is valid markdown for a bold code span and keeps the code text and the bold style the author gave (src/sheafmd/edit.py `_styled_marks`, :155-170).

### 417 (PR 483)

The guard is the design: a refresh that sees the stamp move keeps what the tabs hold and the watcher comes back (src/sheafmd/hub/live.py:636-645); starving needs a file rewritten faster than one render, with no data lost.

### 418 (PR 483)

The claim is wrong in code: `catch_up` sets `e.last_stat = key` after `_refreshed` whatever it returned (src/sheafmd/hub/core.py:1650-1654), and the key is the stat taken before the refresh, so a write landing during the render makes the next request's stat differ and catch up; serving the last good page once is documented (core.py:1655-1659 docstring).

### 422 (PR 484)

Not fixable in the page: the Web Locks API cannot cancel a request already granted whose callback has not run, and that callback runs on resume (src/sheafmd/page/live.js:231-235, :252-258); the window is the one the PR narrowed.


## Already fixed on main

### 407 (PR 481)

The drop is pinned: tests/test_edit_followups.py:687-688 have a `<br>` directly beside a `<div>` (the `_beside_a_block` path, src/sheafmd/edit.py:116-122), and :541, :633, :636 cover the neighbouring cases.


## Unknown: needs a run

### 332 (PR 450)

Claim visible in code: pagehelp.py:557-562 clears `__leaving` when `defaultPrevented`/`returnValue` is set, and page.js:4195 sets both on unload with unsaved edits. Whether Chromium (headless, no sticky user activation) proceeds with the navigation, and what close_context then does, needs a browser run: a reload of a dirty page with no prior click, on the CI runner host, checking `__leaving` against the page's actual navigation.
