# Release note draft: changes on main since sheafmd 1.3.0 (2026-11-23)

Base: the `v1.3.0` tag (84404d00) is not an ancestor of today's main. Main was rewritten after the tag; the same merge of #558 sits on main as d2a08fd0, and its tree matches the tag. 111 pull requests merged since then (#491 to #636; #491, #494, #518 to #533 were merged after the tag even though their numbers are lower). `__version__` on main is still 1.3.0. Below are the ones an installer sees; about 40 others are CI, tests and notes (one line at the end).
**⚑** = needs the next release before another track can rely on it (a box pins a released version).

## Install prerequisite (already met by 1.3.0)
- Ticket 168: a box's hub must run sheafmd >= 1.3.0 before the mail module that writes "Belongs to" is installed there (#480 is in 1.3.0). This is a deploy step, not a new release.

## Peer check (who owns a connection)
- ⚑ A read of `/proc/net/tcp` is no snapshot: one socket per (uid, inode), a second read, a self-test on the set of uids (#636).
- ⚑ A peer self-test that raises leaves the check on (#585); `sheaf open` warns when the hub's self-test failed (#579) and when the platform has no peer check, including once on darwin (#574, #593).
- ⚑ Closed callers are identified by inode, and a refused peer is throttled per kind (#572). SPEC and README say the key and the cookie are judged by the connecting user (#561).

## Hub
- ⚑ Generated pages (ticket 156): a generated rectoverso refuses a fork, `/_/sessions` answers 403, The List draws it no button (#573); `create`'s generated mark and its take-back (#622).
- Root moves and saves: a door update, a page save or the sweep moves no file of a root that took the name after the write found it (#595, #599, #602, #603, #605).
- Forget, delete and the moves' lock: #491, #608, #611, #626, #630, #633; trash and folder rename (#627, #628); the sweep drops marks of addresses with no page (#635); a refused delete still takes the address's marks (#632).
- Pins: the cap of 16 is per member, not per document (#590); a pin in memory expires like one on disk (#543).
- Stop and start: no hub spawned over a stop that won; tabs are told the reason (#606, #621); a command carries the expected boot id (#518); one stop path and a per-platform service object (#575, #577); launchd exit-75 check (#613).
- Live stream: the writer waits to be told, rejoin on refusal or pageshow, a tab joins only once its lock is granted, a late join keeps the newer stream (#537, #539, #568, #588, #601).
- Smaller fixes from the rechecks: #526, #528, #535, #536, #548, #550, #554, #569, #570, #615 to #619, #624, #625 (failed link probe not cached), #631, #634.

## MCP door
- ⚑ `documents` applies the count limit after visibility, once per root; waiting Tells are always listed (#610).
- ⚑ The door table names generated pages; unread has one last author (#612). Door write keeps its root; restart token per process (#599).
- mcp, send and lifecycle items (#536, #616); Accept parsed as a media-type list (#531, #574).

## CLI
- `sheaf send` keeps its state under a lock, and pull re-reads before it writes (#548); CLI recheck items (#556); sign-in link advice per platform (#574).

## Stored formats
- An ordered item with `[ ]` is a task item with a box (#494, #599 for ordered HTML items); a box in a list with raw HTML carrying a data attribute ticks (#555).
- A page edit keeps links, bare URLs, emoji, backslashes in cells and typed breaks in tables (#541, #576, #581, #591, #594, #600, #604, #607); Enter in a heading splits it (#571); comment anchors beside unmatched closing tags (#523, #631, #634); merged saves do not duplicate or resurrect deleted lines (#549).

## Page
- Paste from an online word processor: captured clipboards, two breaks make a paragraph (#559); shortcode follow-ups (#529); Remote Control notice and refusals (#527); edit and page recheck items (#538, #552, #617).

## CI, tests, notes (no installer effect)
#530 #533 #544 #545 #546 #547 #551 #553 #557 #560 #562 to #567 #578 #582 to #584 #586 #587 #589 #592 #596 to #598 #609 #614 #620 #623 #629.
