# Minor findings from the Opus recheck of sheaf PRs #384–#487 and #498

**What to build:** The Opus recheck of the merged range of 81 PRs (Codex out of tokens until 23:15Z) found no serious defect and 221 minor findings, listed below by PR. Each line names a file and line at the merge commit; check it against main before acting, since many PRs touched the same files afterwards.

## PR #384

- [ ] src/sheafmd/mcp.py:946 docstring of _owned still says "sheaf that is its owner's alone" on its second line; the rename missed it (comment only)
- [ ] src/sheafmd/page/page.js:142 comment still says "James on his sheaf"; the rename missed it (comment only)

## PR #385

- [ ] src/sheafmd/hub/core.py:853 render() of an already-open document now calls live.refresh() (via _refreshed) outside any try; before this PR the render path did not refresh, so a file that fails to render now raises out of render() where it used to return OK, and when settings also changed the tabs get two `changed` events (refresh, then rebuild).
- [ ] src/sheafmd/hub/writelog.py:497 `_pulling` is a set, not a count, and Commits._pull calls pulling() before taking the guard/repo lock (commits.py:633): two pulls of the same repo that overlap share one flag, so the first to end clears it while the second is still moving the file, and a disk write that lands while a pull waits for the lock is not logged.
- [ ] src/sheafmd/hub/core.py:227 Hub.pulled loops over files and calls _page_of per file; if _page_of raises for one file, Commits._tell catches it and the remaining addresses never get end_pull, so they stay in `_pulling` and every later disk write to them goes unlogged until the hub restarts.
- [ ] src/sheafmd/mcp.py:911 expect_own is set before the file write; when the write then fails (the move or the commit raises), the stale hash stays until the next refresh, and a later disk write of exactly that text would be taken for the door's own. Also core.py:185 short-circuits: when is_pull is true, is_own is not evaluated, so a pending _own entry is left in place.

## PR #386

- [x] src/sheafmd/hub/loose.py:186 drop() compares the unresolved Path(folder) (built from paths.state_dir()) with root.path, which root_for checks equals realpath(folder); when the state dir path holds a symlink the two never match and a refused first create leaves its empty loose root registered (harmless: the member's next create reuses it). **[fixed on main 4a34dd8c, src/sheafmd/hub/loose.py:304: drop() now compares os.path.realpath(folder) with os.path.realpath(root.path).]**
- [ ] src/sheafmd/hub/loose.py:188 drop() runs inside _create's except BaseException; an OSError from os.rmdir (a concurrent create by the same member filling the folder between listdir and rmdir) or from forget_root replaces the original refusal and leaves loose.json pointing at a forgotten root until the next attach.
- [x] src/sheafmd/mcp.py:796 the bare-name test runs on the raw doc before _named() strips it: " x.md" becomes a page named " x.md" with a leading space, and "x.md " is refused as not .md. **[fixed on main: #525, 65da1f24, test first, red on main]**
- [x] src/sheafmd/mcp.py:798 keep=false on a rooted or absolute doc is refused ("keep is for a loose page"); only a true keep needs refusing. **[fixed on main 4a34dd8c, src/sheafmd/mcp.py:991: Non-bare doc refuses only a true keep (`if args.get("keep")`), keep=false passes.]**
- [x] src/sheafmd/mcp.py:945 expect_own is now recorded for every create (not only loose) before the write; a create refused after it leaves the hash in writes._own until a later change pops it, so a later external write of the identical text to that address would be taken as the door's own. **[fixed on main 4a34dd8c, src/sheafmd/mcp.py:1174: The create path calls writes.told(address) in its except BaseException after expect_own (mcp.py:1165), so a refused create leaves no stale hash.]**

## PR #387

- [x] src/sheafmd/hub/sheaf_view.py:126-130 Titles is one dict shared by the ThreadingHTTPServer threads with no lock; when the cache reaches TITLES_KEPT (5000), another thread's clear() between `self._kept[key] = ...` and `return self._kept[key]` raises KeyError (not OSError), so that /_/mount?sheaf=1 request answers 500. Rare, recovers on retry; return the computed title from a local instead of re-reading the dict. **[fixed on main: #525, 65da1f24, test first, red on main]**
- [ ] src/sheafmd/hub/sheaf_view.py:201 last() and last_session() take the Write log lock separately; a write landing between them can pair a newer session line with an older last line, so the row reads "X, before Y" for a moment. Cosmetic, next mount is right.
- [ ] src/sheafmd/page/mount.js:437 the Sheaf wrapper carries the class `sheaf-list` as well as `sheaf-sheaf`, so every list.css rule scoped to .sheaf-list also applies to the Sheaf's tree and table; styling coupling only.
- [x] src/sheafmd/hub/sheaf_view.py:194-200 each request reads the title of every listed .md (up to 2,000 per root) under its name's lock on first view; cost grows with roots, cached afterwards by (path, mtime, size). **[does not hold on main 4a34dd8c, src/sheafmd/hub/sheaf_view.py:194: Not a defect: a cost remark, and Titles caches by (path, mtime, size) (sheaf_view.py:36-44) as the finding itself says.]**

## PR #388

- [x] src/sheafmd/connect.py:307 make_default tests `.get("tiroir")` for truthiness: a config.toml holding `tiroir = ""` gets a second `tiroir = "https://..."` line, and tomllib then refuses the whole file ("Cannot overwrite a value", reproduced), so every sheaf command stops on a ConfigError until the line is removed by hand. Test `"tiroir" in data` instead. **[fixed on main 4a34dd8c, src/sheafmd/connect.py:280: _with_default has an `empty` regex that fills an empty `tiroir = ""` line in place and then verifies with tomllib, so no second key is written.]**
- [x] src/sheafmd/connect.py:307 a ConfigError from read_toml (broken config.toml) surfaces after the keyring and ~/.claude.json were already written; cmd_connect catches only ConnectError, so the "what was left unwritten" message is not given (main's ConfigError handler at cli.py:1221 prints the error cleanly, no traceback). **[fixed on main 4a34dd8c, src/sheafmd/connect.py:320: connect() runs check_config(origin) before store.set and add_mcp_entry, converting ConfigError to ConnectError "Nothing was written."]**
- [ ] src/sheafmd/connect.py:291-299 ~/.claude.json is read, modified and replaced without any lock while running Claude Code sessions also rewrite it: a write of theirs between the read and os.replace is lost.
- [ ] src/sheafmd/connect.py:247 r.read(1 << 20) on a 200 event-stream answer that is held open blocks until the server closes it; TIMEOUT is per socket operation, so a door that sends keep-alives keeps `sheaf connect` waiting.
- [ ] src/sheafmd/hub/laptops.py:34 laptops.of drops rows marked invalid, so a laptop row that becomes invalid cannot be listed or revoked through /_/laptops/revoke (only `sheaf token revoke laptop-<hex>` on the hub ends it).
- [x] src/sheafmd/cli.py:914 in loopback mode (no [proxy]) a laptop row still signs `Claude Code (<person>)` in _signed_by_others, so `sheaf token add --client "Claude Code"` is refused because of a laptop token the hub itself refuses in that mode. **[fixed on main 4a34dd8c, src/sheafmd/hub/proxy.py:607: signed_names skips a laptop row when cfg is None, so loopback mode no longer counts a laptop token as signed by Claude Code.]**

## PR #389

- [ ] src/sheafmd/mcp.py:1020 reads WriteLog._own (private, outside WriteLog._lock) as a guard; told() is already an idempotent pop under the lock, so the guard is redundant and a call to told() alone would do. Harmless under place.held.
- [ ] src/sheafmd/hub/loose.py:192 drop() now compares realpaths; if the folder recorded in loose.json were itself a symlink to the root, os.rmdir(folder) raises NotADirectoryError after hub.forget_root() has already run, leaving loose.json and the member's roots unchanged. Sheaf makes that folder itself, so this needs a hand-placed link.
- [x] src/sheafmd/mcp.py:798 a non-bool keep is refused only for a non-bare doc; a bare doc with keep="false" (string) is still truthy and marks the page, unless the tool schema (mcp.py:122, boolean) is enforced upstream. **[fixed on main 4a34dd8c, src/sheafmd/mcp.py:253: _check enforces schema type boolean for every call (`keep must be true or false`), so keep="false" is refused for a bare doc too.]**
- [x] PR #389 description does not mention commit 5cde9cff (loose.keep removes the .sheaf folder it made, drop compares real paths, keep=false accepted on a non-bare doc, failed loose create clears its expectation). **[does not hold on main 4a34dd8c, n/a: About the PR #389 description text, not code on main; nothing to change in the repo.]**

## PR #390

- [ ] src/sheafmd/hub/sheaf_view.py:68 a laptop line whose session id is not plain returns None before the ownership check, so another member's session that declared a valid Remote Control link loses it; SPEC 8.6 says any other session with a declared link gives {kind: "remote"}. The name falls back to plain text, so this is a lost link, not a wrong one.
- [ ] src/sheafmd/page/sheaf.js:208 the Remote Control fallback runs window.open inside the fetch rejection handler. If AgentView's address hangs instead of refusing at once, the click's transient activation expires and the popup blocker can drop the tab with no message, because the code returns before say() runs.

## PR #391

- [x] tests/test_proxy_start.py:224-225,238 the scrub renamed first names only: three test member names still carry real surnames (pre-existing in the parent, not newly added by this PR; the public-tree check passed on the merge, so these surnames are not in the check's term list). Replace them with invented names and add the surnames to the term list. **[fixed on main 4a34dd8c, tests/test_proxy_start.py:224: Members are now "Alice Example", "Carol Example", "Bob Example", "Dave Example"; no real surnames remain in the config text.]**
- [ ] tests/test_proxy_start.py:211-215 the docstring still names a private stage and host, and the member UUIDs are described as read off a live box (pre-existing, unchanged by this PR). Rewrite the docstring without them.
- [ ] tests/test_secret_shapes.py:4 the docstring now says "only Alice may override" the Codex runner's secret refusal; a blanket rename turned a statement about the real operator into a fictional one, which no longer describes who overrides it

## PR #393

- [x] src/sheafmd/page/page.js:153 wayBackWhere.say always calls say(t, true), so the informational "this name now opens its Remote Control link directly" shows as a red 7 s error toast and is written as a 'toast' incident (page.js:685); the Sheaf rows show the same text as a neutral line. **[fixed on main: #527, fbde84aa]**
- [ ] src/sheafmd/page/page.js:144 a member page loaded without the mount bundle (sheaf.js only ships in MOUNT_ASSETS, hub/assets.py:16) shows the session name as plain text with no link, so the byline's way back exists only on the mounted page; matches the PR's stated fallback, not documented in SPEC 6.2 item 11.

## PR #394

- [ ] src/sheafmd/hub/handler.py:1019 `_share` builds the tick edit from `e.live.current()[1]` after releasing the name's lock, but passes `after` as the save's base hash; if another writer lands between the two lock regions, `LiveDocument.save` merges an edit whose block index `i` was computed on the newer text as if it were against `after` (live.py `merge_edits(base, text, edits)`), so it can tick or overwrite the wrong block. Compute the edit from the text whose hash is `after` (capture it in `change`). Window is the gap between two lock acquisitions in one request.
- [ ] src/sheafmd/hub/core.py:1090 `may_open` (the save guard's under-lock recheck) returns True for any member on a loose page with a plain Share later narrowed to names, because the loose page keeps `visibility: project` (names_only is skipped for loose roots) and `may_open` does not ask `shared_with`/`member_owns`; only the pre-lock gate `_owned` does. A save by a member dropped from the names in the gap between gate and lock is written.
- [ ] src/sheafmd/mcp.py:454 `_told_text` uses `str.replace(real, told)` on the whole error text, so a real address that is a prefix of another address in the same text is rewritten inside it too (cosmetic).
- [x] src/sheafmd/hub/loose.py:182 `Loose.owner_of` re-reads loose.json and realpaths every folder on each call; it is now called several times per row and per stream event (`loose_owner`, `giver`, `shared_with`, `mine`). Performance only. **[fixed on main 4a34dd8c, src/sheafmd/hub/loose.py:289: owner_of reads through _registry(), which a listing holds once via remembered() (loose.py:~180), so loose.json is read once per listing; only the cheap realpath per folder remains.]**

## PR #395

- [x] src/sheafmd/mcp.py:377 Every member door write that declares X-Sheaf-Session now stores a laptop target, including the shipped `sheaf FILE.md` send (src/sheafmd/send.py:119 always sends the header; the library door's sheaf_door.py forwards it). From deploy on, that member's Tells go to session-tells.json, which `documents` and the library door Notice do not list, and no shipped client calls `tells` (the mod and the library pass-through are separate PRs). The page shows "Waiting for ...: it is not listening now" with Cancel, so nothing is lost or hidden, but before this PR those Tells reached the agent through `documents`. Ship the mod and the door pass-through together with this deploy. **[does not hold on main 4a34dd8c, n/a: A deploy-ordering note (ship the mod and library door pass-through with this deploy), not a code defect on main.]**
- [ ] src/sheafmd/page/page.js:2375 `retargets()` drops `agent:<token>` when it equals `targetNow()`. A laptop target's shape is kind "agent" with the same token, so `targetNow()` is `agent:<token>`, and a member whose only agent is that laptop token gets no Retarget button. The target picker also shows that agent as already chosen.
- [ ] src/sheafmd/hub/handler.py:1817 `_retarget` picks the target inside `_reading`, then calls `start_member_tell` and on refusal `targets.restore` outside it. A `/_/target` that lands between them is overwritten by the restore.

## PR #396

- [ ] src/sheafmd/connect.py:104 entry_name for an IPv6 origin strips brackets then maps every colon to "-", so https://[::1]:8443 gives "sheaf---1-8443"; valid but unreadable as an MCP entry name

## PR #397

- [ ] src/sheafmd/send.py:210 tiroir_of reads .sheaf.toml from the file's own folder, not from its root: a loose page in a subfolder of a registered non-git root (SPEC 8.2 rule 2, Roots._find "deepest") ignores the root's `tiroir` and goes to the laptop default (or, when the root names a tiroir with no credential, is sent instead of rendering locally). SPEC 13 row says "its root's .sheaf.toml"; tests only cover the file's own folder (test_send.py:162,170 write to scratch.parent).
- [ ] src/sheafmd/send.py:195 keep_row is an unlocked read-modify-write of sends.json; two parallel sends of different files can drop one row, and the next send of the dropped file then tries `create` and is refused with "exists already ... Rename" (no data lost, page stuck until renamed).
- [x] src/sheafmd/send.py:150,268,279 a malformed door answer (content[0] not a dict, create/read result without doc/hash/text) raises KeyError/AttributeError past the SendError handler and ends in a traceback instead of a one-line message. **[fixed on main: #525, 65da1f24, test first, red on main]**
- [ ] src/sheafmd/send.py:231 _leave_theirs overwrites an existing FILE.tiroir.md without a check, so a merge in progress in that file is replaced.
- [ ] src/sheafmd/send.py:335 pull checks the local hash, then contacts the door, then writes the file: an edit saved in that window is overwritten.

## PR #398

- [ ] docs/design/2026-11-07-agents-and-waiting-tells.md:16 "library-door#241" is a placeholder name with no matching repo, so the cross-reference no longer resolves to an issue a reader can open

## PR #399

- [ ] src/sheafmd/send.py:67 the "cannot trust" branch matches any ssl.SSLError wrapped in URLError, so an SSLEOFError/connection reset during the TLS handshake (an outage, not a bad certificate) exits 1 with "cannot trust" instead of falling back to the laptop hub; and an ssl.SSLError raised bare during r.read() has a string .reason, so it goes to Unreachable: the two TLS paths are classified inconsistently.
- [ ] src/sheafmd/send.py:141 the post-write recovery text says a rerun will answer "a page of that name exists already, and it is this one", but on rerun _create (send.py:277) turns that answer into "exists already ... was not sent from this file. Rename" because no state row was kept; after a timed-out update the rerun's stale-hash check writes FILE.tiroir.md holding the laptop's own text. No data loss, but the guidance does not match what the user sees.
- [x] src/sheafmd/send.py:81 CONNECT_TIMEOUT applies per message, so the worst case before fallback is about 10 s (initialize plus notifications/initialized), not the 5 s the PR description states; SPEC 13 ("5 s each") is accurate. **[does not hold on main 4a34dd8c, src/sheafmd/send.py:49: Concerns the PR description only; SPEC.md:1709 says "5 s each" and the code comment says the messages before a call, so nothing in the repo is wrong.]**

## PR #400

- [ ] src/sheafmd/hub/repos.py:113 _read returns {} for an unparseable reports.json, so the next _write in _settle replaces the file and drops every owner record of every repo; a corrupt file is silently reset instead of refused.
- [ ] src/sheafmd/hub/repos.py:279 `repo not in self._queues` is read outside self._guard; a report racing the drain thread's pop can call provider.token a second time or skip the no-app check for one report. No wrong record follows (the thread re-checks the token).
- [ ] src/sheafmd/hub/repos.py:195 the ssh -G cache self._hosts is written from request threads without a lock and never expires; a changed ~/.ssh/config alias is not seen until restart.
- [x] src/sheafmd/send.py:517 with hub.repos unwired (PR known limit) every repo page on a connected laptop now costs an initialize + tools/call round trip (up to 5 s each when slow) and a revoked token turns a repo-page render into exit 1 where it used to render locally; intended per SPEC 13, but a visible behaviour change for all connected laptops. **[does not hold on main 4a34dd8c, src/sheafmd/hub/server.py:543: hub.repos is now wired (repos_mod.from_config); the remaining round trip is the intended SPEC behaviour, not a defect.]**

## PR #401

- [ ] src/sheafmd/tells_poll.py:48 _origin_of_server/_has_helper read only the top-level mcpServers of ~/.claude.json (connect.claude_json()); a door entry in project scope (.mcp.json or a project block) fails --check/--server, so an MCP write never arms the mod there (fails closed, a sheaf FILE.md send still arms)
- [ ] plugin/sheaf/hooks/core.ts:81 followSession is exported but never called (register.ts does not import it); Poller.session is set in arm() and read nowhere: dead code
- [ ] plugin/sheaf/hooks/register.ts:38 leave() clears held and doors but not p.delivered, so the set of delivered Tell ids grows for the life of the process across /clear and forks (harmless: ids are unique, memory only)
- [x] src/sheafmd/cli.py:1239 behaviour change: an existing file or folder without .md named like any command (pull, headers, connect, ...) is now the command, no longer opened; documented in the help and SPEC 13, ./name still opens it **[does not hold on main 4a34dd8c, src/sheafmd/cli.py:1305: Intended and documented behaviour ("a command name wins over a file of that name: ./name opens the file"), no defect.]**

## PR #402

- [ ] plugin/sheaf/hooks/register.ts:182 restore() runs on every session.start even when the poller is still armed for another id (a /clear that raised no session.end): the new id's entries mix into p.stored, and the later leave() at the first tick clears them all, so the next keepDelivered for the new id overwrites delivered:<new id> without the restored entries. Effect is a possible repeat Tell after a later resume (the accepted direction), not a loss.
- [ ] plugin/sheaf/hooks/register.ts:76 putBack after the Tell's own turn.start (a submit that resolves with `drop` at turn end) puts the Tell back in `held` and drops it from `delivered`, while p.stored and the store keep it: in-process it is submitted again, after a resume it is not. Pre-existing resubmit semantics; the two sets now disagree.
- [ ] plugin/sheaf/hooks/register.ts:193 a Tell whose turn.start text is non-empty and does not contain t.message (e.g. a runtime that rewrites the prompt) is never remembered and `starting` stays set until the next takeNext; the next main turn with empty text then records it. Errs toward a repeat, as documented.

## PR #403

- [ ] src/sheafmd/hub/core.py:1092 may_open judges the Share line by re-reading the file from disk (opened_by_line with text=None), not the text read under the lock that `fm` came from; the save guard (handler.py:1100) can therefore decide on a newer/older file than the one it writes over. Pre-existing for `named` on shared roots, now extended to loose roots; passing the locked text through would close it.
- [ ] src/sheafmd/hub/core.py:1084 visible() now reads and parses the whole file a second time (opened_by_line) for every page of another member's loose root that visible_to refuses, on each listing/stream poll, bypassing the _front cache judged() keeps.
- [ ] src/sheafmd/hub/core.py:941 shared_with (member_owns) still has no private-source check, unlike opened_by_line; access stays closed only because visible/may_open are also consulted. Two readers of the same rule can drift.

## PR #404

- [ ] src/sheafmd/mcp.py:1165 on a client tiroir an update by the owner's own agent that unticks a ticked `Share with` line is refused (the (ticked, label) tuple changes, so the Counter difference is non-empty), while deleting the same line outright is accepted; the two ways of closing a Share are treated differently (it matches SPEC 9.11's "send back the lines unchanged", but the error text says "add or change", which reads oddly for an untick)
- [ ] src/sheafmd/hub/proxy.py:412 the start check accepts an agency member whose `short` starts with `.` or `-` (allowed by _SHORT_RE), but _BOX_RE/_NAMES_RE in visibility.py only parse names that start with [A-Za-z0-9_], so such a member can never be named in `Share with` and an agent on that tiroir can Share with nobody, which is exactly what the check is there to prevent
- [ ] src/sheafmd/hub/proxy.py:78 the filtered-dict line is over 130 characters and filters OPTIONAL_TABLE_KEYS twice (lines 78 and 81); a small helper would make it read more easily

## PR #405

- [ ] src/sheafmd/hub/moves.py:98 a page can never be moved to the top of its loose root: `loose.folder_path` refuses an empty folder (400), so a top-level page moved into a folder has no way back, and the Move form prefills "" for a top-level page (src/sheafmd/page/sheaf.js:345), which the hub then refuses.
- [ ] src/sheafmd/hub/state.py:324 `_Store.rename` (and Versions.rename, state.py:254) returns without touching `new` when `old` has no entry, so a stale entry already at `new` stays; the docstring says new's own is replaced.
- [ ] src/sheafmd/mcp.py:1187 door `move` reads `self.hub.file(new)` after the moves' lock is released; a Delete or another Move of the page in that window raises an unhandled FileNotFoundError instead of a ToolError.
- [ ] src/sheafmd/hub/archive.py:263 `before = os.lstat(src)` sits outside the try: a trash entry purged between the earlier check and this lstat gives a FileNotFoundError that the route does not map to 404/409.
- [ ] src/sheafmd/hub/moves.py:228 `_undo` writes back the whole forwards.json snapshot; `Hub.forget_root` (core.py:894, `forwards.forget_prefix`) does not take the moves' lock, so a root forgotten during a failing folder move gets its Forwards back.

## PR #406

- [x] src/sheafmd/hub/repos.py:63 _git_version is @functools.cache'd including a None result, so one transient failure of `git --version` (timeout under load, OSError) disables the request-path look for the hub's whole lifetime; caching only a successful read would avoid that. **[fixed on main 4a34dd8c, src/sheafmd/hub/repos.py:80: _cache_good (introduced for _git_version) caches only a non-None read and retries after RETRY_READ_EVERY=60 s.]**
- [ ] src/sheafmd/hub/repos.py:314 on a git before 2.44 every ok report returns commit_known False, so `sheaf` (send.py:495) prints "could not find commit ... is it pushed to GitHub?" for commits that are pushed and held by the clone; the page still renders locally as on the True path (send.py:499-503), so only the message is wrong, but the hub logs nothing to tell an operator why.

## PR #407

- [ ] src/sheafmd/hub/commits.py:121 root_config forces commit=True, push=True on any root with `clone` set, but Hub.clone_of/read_only_line (core.py:358) return "" when hub.repos is None: a hub restarted without [proxy.repos] keeps the clone roots in roots.json, applies no read-only check and no token, and a write by the hub's person on such a page commits on the clone's HEAD (the default branch) and tries to push it. Gate the forced settings on the same condition, or refuse writes to a clone root when repos is None.
- [ ] src/sheafmd/hub/repos.py:604 decide() without a token (saves_on after a restart) reads `origin/HEAD:.sheaf.toml` with GIT_NO_LAZY_FETCH; when that blob is not in the blobless clone (HEAD on another branch whose .sheaf.toml differs), `named` is None and the clone is cached read-only until the next render report, though the named branch exists. Fails safe (read-only), not wrong-branch.
- [x] src/sheafmd/mcp.py:1166 (and mcp.py:620 `_write`, mcp.py:1047 `_created`) the door's `_writable` runs before the visibility check, so a caller who cannot see the page gets the read-only line (repo name, default branch) instead of the missing-document answer. The line does not depend on whether the page exists; it does tell that the clone root is served. **[does not hold on main 4a34dd8c, src/sheafmd/mcp.py:420: In _update, _reply and _move the address comes from _address, which judges visibility first (mcp.py:422-438); _created checks root ownership before _writable (mcp.py:1052-1059), so the read-only line is not shown to a caller who cannot see the page.]**
- [ ] src/sheafmd/hub/repos.py:643 a stale `_why` from an earlier failed switch is shown as the reason while HEAD is off the branch, even after the decided branch changed (e.g. dev appeared); the text can name a cause that no longer applies until the next switch attempt.
- [ ] src/sheafmd/hub/proxy.py:424 the new owner-name uniqueness check compares each member's owner key (short, else id) only; SPEC says a member's short or id is checked against every other member's short AND id. Member A short "nell" plus member B id "nell" with short "bea" starts without error. Matching stays unambiguous (owner_of matches owner_key only), so this is a SPEC/code mismatch, not a wrong owner.
- [x] src/sheafmd/hub/visibility.py:170 owner_of now matches a member without a `short` by their id on every root, not only clones: a non-clone page whose `owner` equals such a member's id now becomes theirs (it matched nobody before). This is intended per SPEC, but it widens access on existing pages. **[does not hold on main 4a34dd8c, src/sheafmd/hub/visibility.py:169: owner_of matching on owner_key (short, else id) is the SPEC.md:997 behaviour, as the finding itself says; not a defect.]**

## PR #408

- [x] src/sheafmd/hub/archive.py:238 restore_trash uses os.rename with the comment "rename, not replace: a page that came in between is not overwritten"; on Linux os.rename replaces an existing file silently, so the only guard is the lexists check under loose-keep.lock, and a writer that does not take that lock and creates the page between the check and the rename is overwritten. Window is microseconds; use os.link+unlink or renameat2(RENAME_NOREPLACE) to make the comment true. **[fixed on main 4a34dd8c, src/sheafmd/hub/archive.py:253: restore_trash now uses os.link (no replace) under file_lock(dest) and loose-keep.lock, with a Taken check (commit c10c4f69).]**
- [x] src/sheafmd/hub/archive.py:141-148 _sweep_root reads Marks and later stamps ARCHIVED without holding loose-keep.lock across both; a Restore or Keep by the owner that lands between the read and the stamp is undone (the page is re-archived, a just-kept page shows archived). Narrow window, recoverable by another Restore. **[fixed on main 4a34dd8c, src/sheafmd/hub/archive.py:136: _sweep_root now reads Marks and stamps ARCHIVED in one hold of loose-keep.lock.]**
- [ ] src/sheafmd/hub/repos.py:205 if a previous _wake failed (git non-zero), "restore" stays; a later sleep overwrites it with the current shrunk listing, so the folders to widen again are lost (they come back on demand through _widen per report).
- [ ] src/sheafmd/hub/archive.py:246-257 purge scandirs .sheaf/trash following a symlinked .sheaf or .sheaf/trash (only the stamp entries are checked with follow_symlinks=False), so rmtree can act on digit-named folders older than 30 days in a linked target; trash() refuses linked folders, purge does not. Needs the owner to plant the link.
- [ ] src/sheafmd/hub/sheaf_view.py:161-165 marks_of applies the owner's archived marks to rows shared with another member, so a recipient's shared page leaves their default view when the owner archives it; recipients get no Restore button for it. Not stated in the PR.
- [ ] src/sheafmd/hub/archive.py:141 seen.json and archived.json are only pruned by trash() (line 202-204); pages removed or renamed outside Delete leave their entries; archived.json and seen.json grow with dead names.

## PR #409

- [ ] src/sheafmd/hub/repos.py:80 the lock is held across `git --version` (timeout 10 s), so while one read hangs every other caller, including _look_is_safe on the request path, waits up to 10 s instead of getting None at once; bounded and only during a read, so not a defect
- [ ] src/sheafmd/hub/repos.py:170 the "said once, at the hub's start" message is printed on every Repos() construction, not once per process; true only because the tiroir builds one Repos per hub
- [ ] tests/test_repo_pages.py:1162 the start-message tests replace _git_version with a lambda and never check that a real failed read at start is later announced as recovered; the recovery line is only covered by the cache test

## PR #410

- [x] src/sheafmd/page/page.js:3017 the Team tab renders a reply as r.body, but team._shape goes through comments.Comment.as_dict, which emits each reply's text as "text" (comments.py:170-171); a reply made through POST /_/team (op reply) shows up as the author's name with an empty body **[fixed on main 4a34dd8c, src/sheafmd/page/page.js:3133: Reply now renders the reply's text field (esc(r.text)); fixed by commit 9d49bd10 "Team tab: a reply shows its text".]**
- [x] src/sheafmd/hub/handler.py:1072 _with_team json.loads the client page's meta block (op "page") outside any try; a meta block that is not valid JSON turns the relayed 200 page into a 500, while the doc/mount branch falls back to the body unchanged **[fixed on main: #525, 65da1f24, test first, red on main]**
- [ ] src/sheafmd/hub/team.py:56 Team comments are keyed by the agency-side address Clients/<client>/<path>; when the client moves or renames the page, its Team comments stay on the old address and are no longer shown (no Forward is followed)

## PR #411

- [ ] src/sheafmd/hub/incoming.py:115-125 the rollback after a failed landing unlinks the file, versions and in-memory Write log lines, but not what door._create already did: hub.wrote/committed (index entry, a commit in a git-backed root), the loose folders _create made, and the on-disk Write log lines appended by writes.carry (writelog.py:183 drop() is memory-only), so a retry of the same page after a restart shows the carried lines twice
- [ ] src/sheafmd/hub/incoming.py:108 versions go to hub.versions (state-dir store) unconditionally, not to the store core._versions_of picks for the root; for a loose root with versions = "root" they would land in the wrong store
- [ ] src/sheafmd/hub/incoming.py:88 transfers.json is keyed by the sender-chosen id alone, not by peer: one peer that sends another peer's id gets that transfer's answer (address, hash, origin) back instead of a landing
- [ ] src/sheafmd/hub/incoming.py:84 owner_for runs before transfers.lock and the id lookup, so a retry of an id that already landed is answered no_owner/ambiguous_owner if the member's e-mail changed in between, instead of the recorded answer
- [ ] src/sheafmd/hub/writelog.py:113 the "came by transfer" line's writer is the sender-supplied from.by, unchecked beyond clean(); a peer names whoever it likes as the writer

## PR #412

- [ ] src/sheafmd/hub/handler.py:1093 `holds_loose(m, doc) or visible(...)` makes `visible` dead for the owner (owner_of(root) == m.id already implies holds_loose), so rule A and the file-read checks inside `visible` no longer run for Archive/Keep/Delete; `Archive.trash` (archive.py:201) lstat-s only the last path component, so a folder link placed in a loose root by someone with filesystem access would let Delete move a file from outside the root. Not reachable by a remote member through the hub; worth an explicit `os.path.realpath` containment check in `trash`.
- [ ] src/sheafmd/hub/handler.py:322 a FileNotFoundError/NotFound on a request whose doc is missing is now answered 404 without `record_exception`, so a genuine bug on that path no longer reaches `sheaf diag`.
- [x] src/sheafmd/hub/archive.py:261 `os.unlink(src)` after a successful `os.link` is unguarded: if it fails the page exists at both the address and in the trash and the request answers 500. **[fixed on main 4a34dd8c, src/sheafmd/hub/archive.py:250: The unlink after os.link is now guarded: except OSError calls _drop(dest) and raises loose.Refused (409), so the page is not left at both places.]**
- [ ] src/sheafmd/hub/archive.py:256 `os.link` on a filesystem without hard links (vfat, some FUSE mounts) now refuses every Restore-trash with 409, where `os.rename` worked.

## PR #415

- [ ] src/sheafmd/hub/readthrough.py:67 is_clients reserves the exact name `Clients` on every hub (loopback included), but roots.py:337 only stops a newly auto-named root from taking it: a root registered as `Clients` before this PR, or a clone root added with an explicit `name="Clients"` (roots.py `_add`, name branch), now answers 403 from `_entry`/`_entry_to_write` and 404 from `_page`'s relay for every page, with no start-time check or message. A lowercase `clients` root (present in the local registry) is unaffected, since is_clients is case-sensitive.
- [ ] src/sheafmd/hub/readthrough.py:59 adopt keeps the client's `rd-edit-meta` JSON block verbatim, so a compromised client tiroir sets the page config (doc, edit, actions) that page.js uses on the agency origin; the CSP (auth.py:75, nonce-only script-src) stops any code, so the reach is limited to what the member then clicks under their own session.
- [ ] src/sheafmd/hub/readthrough.py:61 the page script survives only when the client's inline page.js is byte-identical to this hub's; a client tiroir on another sheaf build serves its relayed pages with no page script at all (no comment forms, no polling), silently. The mount route rewrites the build fields, the page route has no equivalent.

## PR #416

- [ ] src/sheafmd/hub/incoming.py:201 check_root marks a takeable page {"ready": True}, while send_root (src/sheafmd/hub/outgoing.py:83) only counts a page as confirmed on {"ok": True}; wired directly together every page would be held as "failed". Part 2's land_root must answer "ok", or the two must be aligned. Neither function has a caller in src at d1bf68ef, so nothing runs this today.
- [ ] src/sheafmd/hub/outgoing.py:78 send_root calls answer.get(...) without checking that the peer's body is a dict; a peer answering a JSON list or string raises AttributeError instead of holding the batch as "failed". send_root has no caller yet.
- [ ] src/sheafmd/hub/root_moves.py:95 Moves.sent and Moves.hold index row["sent"] / row["held"] directly; a root_moves.json row missing those keys (hand-edited or from an older shape) raises KeyError, although _read treats an unreadable file as empty.
- [ ] src/sheafmd/hub/incoming.py:143 _root_shape accepts an empty owner_email and duplicate page paths; owner_for turns the empty one into no_email and a duplicate is judged twice under one key, so no wrong result follows, but the shape check is looser than its message says.
- [ ] src/sheafmd/send.py:498 moved_to from the hub is printed to the terminal unfiltered (no control-character stripping); the hub is the member's own tiroir, so this is hardening only.

## PR #417

- [x] tests/conftest.py:308 the guard covers os.kill only; os.killpg (used by signals.send_group in hub/commits.py, hub/jobs.py, hub/tell.py) is not wrapped, so a group signal to a process group the test did not start is not refused **[does not hold on main 4a34dd8c, tests/conftest.py:325: signals.send_group (src/sheafmd/signals.py:92) takes only a Popen child that leads its own group and refuses anything else, so a group signal to a process the test did not start cannot be sent; no killpg guard is needed.]**
- [x] tests/test_real_hub_untouched.py:84 `while proc_state(done.pid) == "alive": pass` spins a core with no sleep and no deadline until the child exits **[fixed on main 4a34dd8c, tests/test_real_hub_untouched.py:86: The spin loop is replaced by wait_until_ended(done.pid), which has a deadline.]**
- [ ] tests/conftest.py:314 a refused signal to a live process whose environ cannot be read (another user's) waits the full EXEC_WINDOW (1 s) in is_ending before the AssertionError

## PR #422

- [x] src/sheafmd/hub/outgoing.py:56 `urllib.request.urlopen` follows a 3xx and copies the `Authorization: Bearer <peer token>` header onto the redirected request (urllib's redirect_request keeps all non-content headers), so a paired tiroir that answers 302 hands the peer token to the redirect target; use the `connect._NO_REDIRECT` opener as send.py does (already listed as a follow-up in the PR). **[fixed on main 4a34dd8c, src/sheafmd/hub/outgoing.py:59: post now opens through connect._NO_REDIRECT, so the bearer is not sent to a redirect target (commit 9921afbf).]**
- [x] src/sheafmd/hub/writelog.py:207 `WriteLog.restore` undoes a failed landing in memory only; the carried lines and the `transfer` line stay in the append-only log file and reappear at that address after a hub restart (already listed as a follow-up in the PR). **[fixed on main 4a34dd8c, src/sheafmd/hub/writelog.py:243: undo and restore append a `retracted` line and the kept lines to the file, so a restart does not bring the carried lines back (commits 9921afbf, 2b0db61e).]**
- [x] src/sheafmd/hub/incoming.py:155 `_unkeep` and `_unarchive` share one `contextlib.suppress` block, so when `_unkeep` raises `loose.Refused`/`OSError` the archived mark the landing wrote is not taken back. **[fixed on main: #525, 65da1f24, test first, red on main]**
- [ ] src/sheafmd/hub/outgoing.py:56 the sender's `timeout` is urllib's per-socket-operation timeout while the receiver's deadline counts from `Req.arrived`; a landing that finishes just under the receiver's deadline can reach a sender that has already timed out. The kept `outgoing.json` id makes the resend land once, but a page edited in between gets a new id and is refused `name_taken` on the other side (two copies, no loss).

## PR #423

- [ ] tests/test_helpers_wait.py:23 the unreaped-process test asserts nothing after the wait returns; it does not check that proc_state is "zombie" rather than "gone", so it would also pass if the helper returned for the wrong reason

## PR #425

- [ ] src/sheafmd/hub/archive.py:142 Pre-existing, not touched by this PR: `_sweep_root` lists pages (`self._pages`) outside any lock and takes only `loose-keep.lock`, not `moves._LOCK`; a Move whose `marks_moved` runs between the listing and the stamp leaves the sweep's SEEN/ARCHIVED stamp at the old path, the same stale-mark shape #425 fixes for the handler acts.
- [ ] src/sheafmd/hub/handler.py:1162 `_own_loose` (membership, `visible`, stat) now runs under the hub-global `moves._LOCK`, so every Archive/Restore/Keep serialises with all Moves and door creates hub-wide; consistent with `_delete` (1190), a throughput cost only.

## PR #426

- [ ] tests/page/test_sheaf_buttons.py:113 asserts own_rows and the file right after the first Delete click without waiting; it holds because sheaf.js:638-642 relabels synchronously and posts nothing, but the assert proves no absence of a delayed POST

## PR #427

- [ ] src/sheafmd/hub/state.py:318 (unchanged by this PR) when write_json fails inside Forwards.drop_leading_to, _change has already replaced self._data with the dropped dict, so the in-memory Forward is gone while forwards.json on disk keeps it; the next _change of any kind re-reads the file and the stale Forward to the deleted address comes back. The new 200 path in handler.py:1196-1199 makes this reachable without a 409; the failure is logged as delete-forward-failed, so it is visible in diagnostics.
- [x] src/sheafmd/hub/handler.py:1198 `except Exception` is broader than the OSError the comment describes; acceptable since the page is already trashed and the traceback is recorded. **[does not hold on main 4a34dd8c, src/sheafmd/hub/handler.py:1548: The comment now says "a Forward that cannot be written is a row in the diagnostics log" and does not claim OSError, so the broad except Exception matches its comment.]**

## PR #428

- [ ] src/sheafmd/hub/incoming.py:192 the no-app refusal on the way-back path adds `install` even when the provider's install_url is "" (the report path at :198 omits an empty one); same answer shape should apply to both.
- [ ] src/sheafmd/hub/repos.py:682 refusal() calls provider.token() (a subprocess, up to 30 s) and report() calls it again right after for a repo with no clone; two token-command runs per way-back check.
- [ ] src/sheafmd/hub/outgoing.py:76 docstring carries a stray run of spaces ("its Forward);     every other page").

## PR #429

- [ ] src/sheafmd/hub/core.py:1553 `_page_of`, `Address.parse` and the `admit`/`tell_live` block sit outside the per-pair try: an exception there aborts the remaining pairs of the pull and reaches Commits._tell, which records it as `write-log-failed` (commits.py:724), a misleading row kind for a failed Forward.
- [ ] src/sheafmd/hub/core.py:1571 the two name locks are taken old-then-new, not in ascending order as SPEC 9.11 states for two names; no deadlock since only the holder of the exclusive moves' lock takes two names (same pattern as moves.py:104), but the code and the SPEC sentence disagree.

## PR #430

- [x] tests/test_repo_pages.py:1059 the new test calls _on_branch on tmp_path, which is not a git clone, so git fails and only the spy filter is exercised, not a real look; adequate for what it asserts **[does not hold on main 4a34dd8c, tests/test_repo_pages.py:1059: Observation that the test asserts only the spy filter on a non-clone dir, which is what its docstring says it tests (which Repos made the look); no defect.]**

## PR #431

- [x] tests/test_hub_lifecycle.py:454 the new guard test monkeypatches sender.cmdline, so it checks the fake (pid <= 2**22) and not /proc; it would stay green if SENDER_PID were set back to any value above 2**22 only, which is the intent, but it does not prove the kernel limit itself (PID_MAX_LIMIT 2**22 on 64-bit; /proc/sys/kernel/pid_max reads 4194304 here) **[does not hold on main 4a34dd8c, tests/test_hub_lifecycle.py:454: Observation, no defect: the test's job is that the made-up SENDER_PID (tests/test_hub_lifecycle.py:234) stays above 2**22 against a faked cmdline; the kernel limit is stated in the comment at :233 and cannot be proved by a test.]**

## PR #432

- [ ] tests/twin_session.py:73 hub.commits.settle() returns False after its 30 s timeout and the result is ignored (also at 110, 112, 124); a pusher stuck past 30 s would let the session go on unsettled and surface later as a byte-for-byte diff instead of a clear failure. `assert hub.commits.settle()` would name the cause.

## PR #434

- [ ] src/sheafmd/page/page.js:1213 a clone page opened before the hub upgrade (old page.js, no CFG.branch) gets a 400 on every save, and its draft (no branch) is then refused by Restore after reload; the edits are kept to copy, not lost, but there is no transition path for in-flight drafts
- [ ] src/sheafmd/hub/handler.py:997 the branch check is skipped on a rid replay (live.save answers `again` before the guard); correct since nothing is written, but the 200 `again` answer hides the switch from the page
- [x] src/sheafmd/hub/core.py:1540 catch_up rebuilds when the recorded branch differs from HEAD; if the rebuild keeps failing, it is retried on every request (bounded by the existing _rebuild_failed path, no crash) **[does not hold on main 4a34dd8c, src/sheafmd/hub/core.py:1668: Not a defect: catch_up's docstring (1656-1659) states a failed rebuild is tried again on the next request, and _rebuild_failed (core.py:1799ff) bounds the logging; the finding itself says no crash.]**

## PR #435

- [ ] tests/test_page_predicates.py:11 A_FUNCTION accepts any string starting with "(", so a parenthesised expression such as "(window.x === 1)" passes the guard although Playwright evaluates it as an expression through eval; anchoring on "\(.*?\)\s*=>" would close that gap.
- [ ] tests/test_page_predicates.py:16 PAGE_TESTS.glob("*.py") scans only the top level of tests/page; a page test in a subdirectory or a helper outside tests/page (e.g. a conftest elsewhere) is not checked.

## PR #438

- [ ] src/sheafmd/hub/repos.py:413 wake() calls _use (sleeping=False) before _restore; when the widen fails (git error, no token) the clone reads as awake, so read_only_line gives the page no "asleep" line while its folders are still out and the next save fails on the missing file. Self-heals on the next write (restore is kept), no data lost.
- [ ] src/sheafmd/hub/repos.py:416 provider.token(repo) (an App token request) runs while holding the clone's non-reentrant commit lock (Commits._repo_lock), so saves, pulls and commits of that repo wait on the token call.
- [ ] src/sheafmd/hub/repos.py:413 every owner write to an awake clone page takes the commit lock and rewrites clones.json via _use: extra lock traffic and a file write per save.
- [ ] src/sheafmd/hub/repos.py:278 sleep_moved updates an already-sleeping row without the clone's lock, so a wake() that passed its moved check can leave the row moved with sleeping=False; read_only_line still refuses (moved is checked first), but a later sleep step on that row records restore=[] over the folders it held.
- [x] src/sheafmd/hub/core.py:380 the absolute-path branch takes realpath(doc) relative to root.path without resolving root.path; a root registered through a symlink raises ValueError, caught, so the write wakes nothing (no crash). **[does not hold on main 4a34dd8c, src/sheafmd/hub/core.py:380: roots.lookup matches only on realpath (roots.py:408, _find compares r.path to a realpath'd folder) and roots are stored realpath'd (roots.py:321), so root.path is already resolved when relative_to runs at core.py:383.]**

## PR #439

- [ ] src/sheafmd/hub/writelog.py:225 WriteLog.drop now appends a `retracted` line, but nothing in src/ or tests/ calls WriteLog.drop at b562023d (git grep), so the new file behaviour is untested and unused.
- [ ] src/sheafmd/hub/writelog.py:218 restore rewrites the file under `address` (replace) but leaves the in-memory deque with the original Line objects, so lines carried by a rename carry their old `address` in memory and the new one after a restart; nothing compares Line.address across that boundary today (carry's `held` Counter only gains matches from it).
- [ ] src/sheafmd/hub/writelog.py:218 each failed landing at a known address re-appends up to KEEP (200) kept lines plus a marker; repeated failed landings grow the file toward MAX_BYTES rotation faster (bounded, no loss beyond the existing rotation behaviour).

## PR #440

- [x] src/sheafmd/connect.py:122 use_peer_file lets OSError from mkdir/os.open escape (cmd_peer catches only ConnectError/TokenError, main has no OSError handler), so an unwritable --dir gives a traceback at f5901098; already fixed on current main (same command now prints "cannot keep the token in /proc/nope ... nothing was written") **[fixed on main 4a34dd8c, src/sheafmd/connect.py:134-153: use_peer_file now wraps mkdir/os.open/replace in `except OSError` and raises ConnectError("cannot keep the token in ... nothing was written").]**
- [x] src/sheafmd/cli.py:1134 `peer add` still tells the user to run `sheaf peer use <address> <token>`, the form this PR documents as discouraged (token in ps/history) **[fixed on main: #522, bf5f0587]**
- [ ] src/sheafmd/connect.py:82 peer_credential_name maps ':' to '-', so https://a.example:8443 and a host literally named a.example-8443 share one credential file name (contrived)
- [ ] src/sheafmd/connect.py:121 an existing --dir keeps its mode; only a newly created folder is 0700 (the file itself is 0600, so the token is not exposed)

## PR #441

- [x] src/sheafmd/connect.py:140 if os.replace(tmp, target) fails, the .new file holding the token stays on disk (outer except converts to ConnectError without unlinking tmp); already fixed after the merge by 6fe7ec3a ("no temp token left on failure") **[fixed on main 4a34dd8c, src/sheafmd/connect.py:134-153: Both except branches (OSError :146, BaseException :149) unlink the temp when `made`, so no .new token is left after a failed os.replace.]**
- [x] src/sheafmd/connect.py:98 the corrupt-credential warning is printed on every peer_token_for call, not once; already fixed after the merge by 6fe7ec3a ("one warning per corrupt credential file") **[fixed on main 4a34dd8c, src/sheafmd/connect.py:98-104: _WARNED (:78) records the file name; the warning prints only when the name is not yet in it, once per process.]**

## PR #442

- [x] src/sheafmd/page/sheaf.js:416 submitting the field unchanged (to == folder) is sent to the hub, which answers 409 "A folder cannot be moved into itself." — a misleading message for a no-op; the form could close or say nothing changed instead **[fixed on main: #527, fbde84aa]**
- [ ] src/sheafmd/page/sheaf.js:396 a refusal is written to the Sheaf's shared status line (say), not beside the open form, so with several Rename/Move forms open the message does not say which one it answers

## PR #443

- [ ] src/sheafmd/connect.py:135 `made = True` is set on the line after os.open returns, so a KeyboardInterrupt delivered between the two leaves the temp behind and the fd open; a one-statement window, not reachable by an ordinary failure.
- [ ] src/sheafmd/connect.py:143 os.close(fd) in `finally` replaces the original write/fsync error if close also fails; the temp is still removed and the message still says nothing was written, only the strerror shown is close's.

## PR #444

- [ ] src/sheafmd/mcp.py:477 Door._asleep answers "no document" to a proxy-mode token bound to no member even when it may see the page (`visibility: project`, which Door._sees grants it), where SPEC 8.6 says any token that may see the page gets the asleep line; error wording only, no data or access effect.

## PR #445

- [ ] tests/public_tree.py:106 tracked() decodes `git ls-files -z` with errors="replace", so a tracked file whose name is not UTF-8 resolves to a path that does not exist and its content is skipped silently by the is_file() check at line 121 (the path itself is still scanned).
- [ ] tests/public_tree.py:142 a name found in a path is reported as `path:0 term N`, and the path printed holds the name; the docstring (line 3) and SPEC row say a hit never prints the matched text. No new exposure (the path is already public), but the claim is not exact.
- [ ] tests/public_tree.py:125 the guard's own two files are exempt from every address any ALLOW entry lists, whatever file that entry names; documented as intended, but it is broader than one entry per file.

## PR #446

- [ ] src/sheafmd/page/mount.js:452 a list/Sheaf page created before the stylesheet wait now stays assigned when that draw goes stale (previously page stayed null); it is unmounted by the next draw (`if (page) page.unmount()`), by handle.unmount(), or by an overtaking mount via pane.live.unmount(), so no leak, but the stale draw's kit is live and clickable until then
- [ ] tests/page/test_mount_sheaf.py:397 the comment says "9 of 240 runs" while the PR body says "about 4 %"; consistent (3.75 %) but the test name/comment cite a specific other test that may be renamed later

## PR #448

- [ ] src/sheafmd/hub/repos.py:289 if t.start() raises (e.g. "can't start new thread"), the unstarted thread stays in `_threads` and the repo in `_queues`, so a later settle() still hits "cannot join thread before it is started" and the repo is blocked; pre-existing, not introduced by this PR (same at :330 and :742)
- [ ] tests/test_clone_sleep.py:136 the red/green signal rests on a 0.5 s join timeout; on a loaded runner the helper's settle() may not reach join() inside 0.5 s on the old code, so the test can pass without exercising the gap (no false failure on the fixed code)

## PR #449

- [x] src/sheafmd/page/page.js:3061 a refused delete (403/410) leaves teamAsk set, so the button still reads "Confirm delete" and the next single click sends the delete again without the two-click ask **[fixed on main: #527, fbde84aa]**
- [ ] src/sheafmd/page/page.js:3033 teamBusy drops every Team-tab click (Reply, Edit, Cancel) while one write is out, not only a second send; the click does nothing and says nothing
- [ ] src/sheafmd/page/page.js:3054 Send with an empty or whitespace-only textarea returns silently, with no message to the member

## PR #450

- [ ] tests/page/pagehelp.py:550 LEAVING_JS clears __leaving whenever a handler called preventDefault/returnValue, but page.js:4064 calls preventDefault on every unload with unsaved edits, and Chromium proceeds with the navigation when the frame has no sticky user activation (no dialog is shown): such a reload is then not seen as leaving, and close_context falls back to the old unguarded close (the e2 hang), not a wrong result.
- [ ] tests/page/conftest.py:183 the tab teardown goes through landed() -> settled(), which waits for #rd-menu-btn; a test that ends leaving for a non-sheaf page would wait PAGE_TIMEOUT_MS and fail, while close_context uses the selector-free landed_page. No current test was found doing that (CI slices 1,3-6 green on the merge commit).
- [ ] tests/page/pagehelp.py:586 settled()/landed() see only a reload that has already begun; a reload that starts after the check is still closed under (acknowledged in the PR as follow-up finding 4).
- [x] CI on merge commit 0268cfc1: slice 2/6 failed in test_page_writing.py::test_a_change_heard_between_a_replys_answer_and_its_end_reloads_when_the_send_ends_and_says_it_waited (toast 'text changed while you wrote' never seen), a test this PR does not touch and a flake already filed as .scratch/chat-box/issues/137 and 141; the branch head 85e27cae was 6/6 green. **[does not hold on main 4a34dd8c, .scratch/chat-box/issues/137, 141: A CI flake record of a test the PR did not touch; already filed as tickets 137 and 141, nothing to fix here.]**

## PR #452

- [ ] tests/test_peer_transfer.py:371 the integration test never reaches `undo`: the slow `versions.put` trips `_in_time` before `carry` adds the landing's first line, so `mine.before` holds no entry for the address and `undo` returns early; it guards against the old blanket `restore(address, [])`, but the line-by-line take-back is covered only by the unit tests in tests/test_write_log.py
- [ ] src/sheafmd/hub/writelog.py:233 docstring names a `Landing` type that does not exist; the object yielded is `_Own`
- [ ] src/sheafmd/hub/writelog.py:249 `undo` subtracts every line in `own.lines`, including lines the landing wrote at other addresses; harmless because `address` is part of Line equality, but filtering by address would state the intent
- [ ] src/sheafmd/hub/writelog.py:10 `import contextlib` placed after `import os`, out of alphabetical order with the rest of the stdlib block

## PR #453

- [ ] tests/test_leakguard.py:249 the test passes only if the real second read happens while the `sleep` child is under EXEC_WINDOW (1.0 s) old, because `_after_exec` loops only while `_is_executing` holds; on a runner stalled for over 1 s between Popen and the call it returns None and the assert fails (a flake, not a product defect)
- [ ] tests/leakguard.py:131 a process that execs more than EXEC_WINDOW after it was started (a long-lived shell running `exec`) still reads as unmarked during the exec, so `guarded_kill` can still raise for it; the same limit already holds for `left_running` at tests/leakguard.py:106, so this is pre-existing and not widened by the PR

## PR #454

- [x] PR #454 description/title are stale: they still describe the `Gate` fixture and the /_/doc wait from round 1, while the merged code (299c9a9a) waits for `#rd-menu` and holds mount.css with a page.route; the commit log is the accurate record. **[does not hold on main 4a34dd8c, GitHub PR #454 text: The finding is about the PR description on GitHub, not a repo file; nothing to change on main.]**
- [ ] tests/page/test_mount_sheaf.py:271 the held-stylesheet test asserts the byline lacks "Claude Code" only via the rendered text; it relies on mount.js:453 awaiting link.onload before create (verified) and page.js:178 takeAgent running before #rd-menu is appended at page.js:604 (verified), so it is correct today but couples to that ordering without a comment at the call sites in src.

## PR #455

- [ ] src/sheafmd/hub/boxwait.py:126 `d.state = state` runs before `_end`, so `_end`'s own `delivered` check misses and the clear is re-done by hand (`was == "delivered"`); correct as written, but setting state after `_end` (or not at all, since the drop is discarded) would remove the duplicated rule
- [ ] src/sheafmd/hub/core.py:1465 the pass settles drops against the file before reading statuses, so when the Starter writes `answered` after its reply (the contract in SPEC 9.15), the reply usually ends the drop first and `answered` is never told to the page; harmless (the reply clears the line), but the new state is mostly unobserved in practice
- [x] tests/test_hub_work.py:760 hub test not run locally (laptop load 10.5, above the limit of 8); the two page tests are Playwright, CI only **[does not hold on main 4a34dd8c, tests/test_hub_work.py:760: A note that the author did not run the test locally; not a defect in code.]**

## PR #457

- [ ] src/sheafmd/page/sheaf.js:435 closing the Laptops panel (or clicking a folder) while POST /_/laptops is in flight drops the answer: the hub has already created the laptop and its token, the line is never shown, and the name stays taken until the member revokes it; closing and reopening the panel before the answer instead shows the line, since only lpanel.hidden is checked, not lseq.
- [ ] src/sheafmd/page/sheaf.js:446 the network-failure path of Connect calls say() even when the panel was closed meanwhile, unlike the success path at 435.
- [ ] src/sheafmd/page/sheaf.js:474 the Copy button keeps the text "Copied" after the next Connect or after the panel is closed and reopened; nothing resets it.

## PR #473

- [ ] src/sheafmd/edit.py:324 EMOJI_ATTR_RE strips data-emoji from any <span>, not only class="emoji" ones; harmless for comparison since _sanitize drops every data- attribute from the fragment anyway, but the comment claims a narrower scope than the regex has.

## PR #474

- [ ] src/sheafmd/hub/handler.py:271 the SHARED_MAX check (keys() then join) is not atomic: concurrent joins of new keys can pass 200 by a few
- [ ] src/sheafmd/hub/handler.py:273 a join that lands after its shared stream closed answers 200 while Shared.join drops the Subscription silently; the tab waits for an `open` that never comes (the leader's EventSource error recovers it)
- [ ] src/sheafmd/hub/server.py:200 a Shared replaced under the same sid (old.close()) keeps its server loop and thread alive, idle, until the peer closes: the loop never checks `sub.closed`
- [ ] src/sheafmd/hub/handler.py:298 `/_/live/leave` with a non-string key answers 200 without checking the stream or its owner (inconsistent with the 404 the SPEC row documents)
- [ ] src/sheafmd/page/live.js:487 every tab that wins the `sheaf-live` lock opens `/_/live?shared=` even when no page in the browser asked for a stream (a read-through page, a page whose document is gone): one idle connection
- [x] PR #474 description (GitHub, not the repo) names a client ("Chien Vert placement sheet"); the merged files add no private names (checked every added line) **[does not hold on main 4a34dd8c, GitHub PR #474 text: About the PR description on GitHub, not a repo file; the finding itself says the merged files add no private names.]**

## PR #475

- [x] src/sheafmd/edit.py:681 the depth walk only treats <table> as raw HTML; any other block pandoc writes as raw HTML (where a backslash is not an escape) would show a doubled backslash. Probed dl, details, div, sup, link text, br: all round-trip correctly today, so no case was found. **[does not hold on main 4a34dd8c, src/sheafmd/edit.py:~764-775: The finding states it probed dl, details, div, sup, link text, br and found no failing case; no defect.]**

## PR #476

- [ ] src/sheafmd/page/page.js:3643 `sc !== box` is dead: box is an <input>, it never contains cont, so `sc.contains(cont)` already excludes it.
- [ ] tests/test_edit_followups.py:1206 the "ordered" and "ordered from three" cases are named task lists, but per the PR's own finding pandoc gfm renders `1. [ ] x` as plain text, so they test a plain ordered list's round trip, not a task list's.

## PR #477

- [ ] src/sheafmd/hub/the_list.py:367 `check` only tests that the block itself renders; when that render succeeds but box_number's render of the flipped content fails (pandoc non-zero exit or 120 s timeout), box_number returns None (uncached) and a real action is dropped for that read. Reproduced on the merge tree: with the flipped render forced to fail, read_rectoverso of "- item / fenced code / - [ ] Done" returns no actions instead of ["Done"]. Transient: the list row loses its button for one poll, and the save guard (handler.py:1662/1666, unticks_one_off / ticks_another_move via _boxes) can misjudge one save. The docstring's "no real action may go" does not hold for this case; falling back to the line reading when box_number cannot render would match it.
- [x] src/sheafmd/hub/the_list.py:368 a block that matches _MAY_HOLD_CODE_RE (any loose list with a 4-space nested item, any line starting with `<`) now costs one pandoc render per action line on first read (box_number renders the flipped content each time), in the poll, core.actions and the save guard; cached afterwards by (content, at), so only the first read of each new text pays it. **[does not hold on main 4a34dd8c, src/sheafmd/hub/the_list.py:368: Describes a one-time render cost per new text (cached by (content, at)); an observation, no defect to fix.]**

## PR #479

- [ ] src/sheafmd/edit.py:725 The token is restored as `:name:` regardless of table depth, so when pandoc writes the table as raw HTML (a cell holding block content such as a list, or the `_cell_breaks` fallback at edit.py:707) the saved cell reads `<th>:+1:</th>` and the next render shows the literal text ":+1:" where the page showed 👍. Observed: source "| :+1: | here |\n|---|---|\n| a | b |" with "here" replaced by "<ul><li>x</li><li>y</li></ul>" saves `<th>:+1:</th>`; with `_emoji_as_tokens` stubbed out (pre-PR behaviour) it saves `<th>👍</th>`. The function's own docstring names this case. Fix: inside `<table` depth substitute the emoji (or the span) instead of the shortcode, as the pipe/slash loop at edit.py:713-720 already does. No content is lost; the shortcode name survives.

## PR #480

- [ ] src/sheafmd/page/page.js:3980 on a legacy `- [ ] Move to <slug> (ref …)` line the hub's label is `Belongs to <slug>`, so hideWord (words `Belongs to <slug>`, `Belongs to`) finds no match and the line shows the button `Belongs to <slug>` followed by the visible text `Move to <slug> (ref …)`: the slug is said twice; cosmetic, legacy pages only. Passing the `Move to` form as a third word would hide it.
- [x] src/sheafmd/hub/the_list.py:446 a page or list loaded before the deploy sends word `Move to` with its press; tick_edit compares against `Belongs to` and returns None, so that one press is refused until the page reloads; transient across the restart only. **[does not hold on main 4a34dd8c, src/sheafmd/hub/the_list.py:443-449: Transient across the ticket 168 restart only (a page loaded before the deploy); the window has passed, no code to change.]**
- [ ] GLOSSARY.md:180 still says "the code still says Move to until ticket 168", and GLOSSARY.md:194 "a Move to is a one-off too": stale now that 168 is merged (GLOSSARY not touched by this PR).

## PR #481

- [ ] src/sheafmd/edit.py:123 _styled_marks also applies inside headings: a pasted '<h2><span style="font-weight:700">Head</span></h2>' saves as '## **Head**' (observed with the merge-commit code); headings could skip the bold mark.
- [ ] src/sheafmd/edit.py:123 a bold-styled span inside <code> saves as '**`c`**' (observed); the code text is kept, but the bold wraps the code span.
- [ ] src/sheafmd/edit.py:116 a <br> that _lines_as_paragraphs/_lines_as_items or the browser placed next to a <div> line is now also dropped when a block follows (e.g. '<li>a<div><br></div><div>b</div></li>' loses one of its breaks); the output was backslash lines before and is fewer backslash lines now, so it is a behaviour change with no test pinning it.

## PR #482

- [ ] src/sheafmd/edit.py:593 table_is_taken is computed before _text_backslashes (edit.py:754) tokenises escapable backslashes, while _cell_breaks (edit.py:648) tests "\\" after it. A table whose only backslashes precede punctuation (cell `a\\*`) is still taken as a pipe table by _cell_breaks, but _without_placeholder_breaks already dropped the break, so the ticket-137 bug survives there: observed `x<br>\xa0\xa0` in a cell next to `a\\*` saved as `| x\xa0\xa0 |` (break lost, Enter's cut no-break space kept). Same output as before the PR, so no regression; the guard should be evaluated on the same fragment _cell_breaks sees.

## PR #483

- [ ] src/sheafmd/hub/live.py:635 the torn text read by `_rerender` is still passed to `_remember` (in-memory versions and the disk store) although the restore path never hands it to a page; harmless, but it pollutes the store with a text no tab holds.
- [ ] src/sheafmd/hub/live.py:636 the second `_stamp()` catches only OSError; a non-OSError from `Entry.stat` (e.g. `place.file_at` failing to decide the file) raised after `_rerender` leaves `_text/_hash/_branch` set to the possibly torn text with nothing published (the restore of `kept` is skipped); the watcher then logs rebuild-failed.
- [ ] src/sheafmd/hub/live.py:636 a file rewritten more often than one render takes never publishes: every refresh sees the stamp move and returns None (starvation, not data loss).
- [ ] src/sheafmd/hub/core.py:1625 `catch_up` for a document with no tab serves the old page when `refresh` returns None; `last_stat` keeps the pre-refresh key, so the next request catches up, but the watcher skips tabless documents, so it waits for that request.

## PR #484

- [ ] src/sheafmd/page/live.js:231 waiting.abort() only cancels a request still in the lock queue; if the browser granted 'sheaf-live' just before `freeze` and the grant callback had not yet run, the abort is a no-op, the callback runs on resume, and the tab holds the lock through the freeze (the case this PR fixes). Narrow window; a self-heal on resume does not exist for it.
- [ ] src/sheafmd/page/live.js:237-242 a non-leader tab frozen while the leader stayed alive fails every open source (_fail(0) -> onerror) and rejoins on resume although its streams were still joined on the live leader; the hub replaces the key (events.py:139 Shared.join), so the result is correct but each page sees a spurious error/open cycle. Combined with the 'who' message queued during the freeze, a tab that resumes after a hand-over joins each key twice (two `open` events, two onopen calls).
- [ ] src/sheafmd/page/live.js:148 an old leader's in-flight /_/live/join (sent before freeze, reaching the hub after the new leader's join for the same key) would run handler.py:919-922 and leave() that key from the new leader's stream; same race as the existing close hand-over, needs the old fetch to outlast the new leader's connect round trip.

## PR #485

- [ ] SPEC.md:1694 The narrowed rule ("every output of the command line stays free of any tiroir mention") is still contradicted by shipped CLI messages: src/sheafmd/connect.py:291 ("has a `tiroir` entry"), src/sheafmd/send.py:613 ("no credential for {row['tiroir']}"), and the send output tests/test_send.py:128 names ("prints the address the tiroir and the folder"); the `tiroir =` key in .sheaf.toml (SPEC.md:239) also surfaces in output. Either the rule or those messages need a follow-up.
- [ ] SPEC.md:1694 "the two places that carry it" is not exhaustive for the spec itself: D9 (SPEC.md:50) and the `tiroir` config key (SPEC.md:239) also name tiroir; wording could say "the two output places".

## PR #486

- [ ] SPEC.md:217 missing full stop before "The hub's own `generated` key" ("...this process made The hub's own...").
- [ ] SPEC.md:681 missing full stop before "A generated document (8.3) is refused" in the /_/tick row ("...true or false A generated...").
- [ ] SPEC.md:694 missing full stop before "A generated document (8.3) is refused" in the /_/save row ("...each remembered A generated...").
- [ ] SPEC.md:1260 and README.md:73 list "Ask" among the controls that keep working, but Ask was retired (SPEC D25, 11.2); drop it.
- [ ] SPEC.md:1678 / SPEC.md:945 do not say what `generated.by` and `generated.id` hold when the key (a caller with no token, no stable id) sets the mark; step 2 needs a rule (e.g. id null, by the X-Sheaf-As name) and what "the setter" means then.
- [ ] SPEC.md:945 every local `sheaf mcp` stdio door holds the hub key (12), so any local agent can update a generated page or clear the mark; the setter-only rule binds HTTP tokens only. Worth one sentence so step 3 does not read it as stronger than it is.
- [ ] SPEC.md:686 `POST /_/share` still writes text (adds/ticks the Share line) on a generated page; left open in the PR description, unresolved in the spec.

## PR #487

- [ ] src/sheafmd/page/page.js:2607 on the new 409 the catch path does not call off(), so the thread keeps its Tell shown as running until reload; harmless because forget_root (core.py:1008-1024) already ended every Tell and job under the forgotten root, but the page shows a stale state next to the "reload the page" error
- [x] src/sheafmd/hub/handler.py:2378 a root forgotten and re-added for the same folder gets a new id, so its old page's cancel is now refused with 409 where it was an ok before; nothing of that page is left running (forget cancelled it), so only the message changes **[does not hold on main 4a34dd8c, src/sheafmd/hub/handler.py:2386: Describes accepted behaviour (only the message changes, nothing left running); no defect to fix.]**

## PR #498

- [ ] tests/page/pagehelp.py:32 rewrite() goes through write_text_atomic with mode=None, so a rewritten file gets the umask default mode instead of keeping its own; no changed test chmods a document today, but a future read-only-file test using rewrite() would silently lose its mode.
- [ ] tests/page/pagehelp.py:32 rewrite() also creates missing parent folders (write_text_atomic mkdirs), where Path.write_text raised; a test that relies on a write failing into a removed folder would no longer fail.

**Blocked by:** None.

**Status:** open
