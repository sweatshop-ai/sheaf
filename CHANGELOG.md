# Changelog

sheafmd is released by merging a pull request that sets `__version__` in `src/sheafmd/__init__.py`.
Its page assets are cached by version (`/_/mount.css?v=<version>`, immutable), so the version
changes whenever an asset does. The entries name pull requests of sweatshop-ai/sheaf.

## Unreleased

### Fixed

- A client page read through an agency tiroir keeps each agency member's unsent comment and edit drafts apart: the agency hub, not the client tiroir, says which member the page is for (#684, from the review of #655).
- `sheaf peer use --store file` keeps the token of a peer whose host is long or non-ASCII: a credential file name that would pass 255 bytes is cut and ends in a hash of the origin (#684, from the review of #655).
- A tab that joins its browser's shared stream while that stream is opened again keeps its place on the fresh stream: the join begun on the old one no longer takes the tab off the fresh one, which left the tab counted nowhere and getting no events (#690).
- Raw HTML with a `data-` attribute right after a `/` (`<div/data-x>`) is compared as the open tag it is, instead of as one that closes itself (`<div/>`), so a block nobody touched is not rewritten (#689).
- Two shortcodes written as text (`\:smile: \:smile:`) in a long changed stretch keep both escapes, instead of one of them showing as its emoji (#689).
- A paragraph with hard breaks of its own (`Alpha\` `\` `Beta`) stays one paragraph when both lines beside the breaks are edited in one save, as long as a word of them is left; two new breaks typed before or after them still make two paragraphs, as do two new breaks with none of those words beside them (#685).
- An empty link target (`<a id="x"></a>`) left at the start of a heading split with Enter goes on with the heading, in its order, instead of being deleted with the empty marks the browser leaves (#685).
- `sheaf open` gets its answer on a slow page: a render the hub has not finished within 120 seconds goes on and publishes its page, and the command says that the next `sheaf open` serves it, instead of failing. Each pandoc run keeps its own 120 seconds, and a wait for the document's lock no longer counts against them.
- `sheaf FILE.md` calls a tiroir's tools under the names the server lists in `tools/list` (`sheaf_create` on a door that prefixes them, `create` on a laptop hub), instead of always sending the bare name, which a door refused with 403. A 403 now shows the door's own words instead of the sentence about a revoked token (a revoked token still answers 401).
- A conflict copy (`FILE.tiroir.md`) is never overwritten: a second conflict leaves the next free name, `FILE.tiroir-2.md`, `-3`, and the same text reuses the copy already there; `pull` does the same.
- A send whose folder git cannot place (git missing, timed out, dubious ownership, unsafe repository) stops with the cause instead of sending the page as a loose one.
- A failure after a write no longer says "Nothing was sent": it says whether the page arrived is not known, and the next run takes up a page that did arrive.
- A pin in a root's own versions store keeps its age through a clone or checkout: its time is in `<hash>.at` beside it, kept out of git by `.sheaf/versions/.gitignore`, so a pin older than 7 days is not believed again. A pin written before has no such file: after the upgrade it counts only once pinned again, so a page that holds its reload across the hub's restart can get "version no longer known" (409) on its save until its next daily pin.
- `sheaf connect` checks that `config.toml` can be written before it stores the token.
- A page opened on its own address keeps the link of its byline's session name (the session kit moved to `session.js`, loaded by the page script and the mount bundle).

## 1.3.0 (2026-11-20)

Everything merged since 1.2.1 (#472), up to #534. Version 1.2.1 was never tagged; this release carries it.

### Added

- A diagram (mermaid or chart) or an SVG image opens in a full-window viewer on a click or tap: wheel and pinch zoom about the pointer, drag to pan, double click or Fit to reset, Esc, the close button or a click outside to close. It works in Comment and Edit mode, on a phone, and in both themes (SPEC 6.9).
- A page a job generates can be marked as generated, read-only for text edits: the mark is set, shown and guarded by the door (#486, #503, #534, ticket 156). The hub refuses a save, a tick or a share on such a page with a sentence that names who generated it; comments, replies and resolve stay open.
- The comment box moves by its band, with a mouse or a finger (#501, ticket 174).
- Resolve in the comment box is a check mark, not a minus (#500, ticket 175).
- The list action `Move to` is now `Belongs to`; a box still carrying the old word is read (#480, ticket 168).
- `sheaf restart` announcements carry a token, so an older restart no longer clears a newer one's (#489, ticket 99).

### Changed

- A stop under way is never overridden by a newer command (#508, ticket 99).
- The door lists a root's files with the hub's own lister, and a root past the cap gets a "more" row (#492, ticket 93).
- One dot cascade serves the index page and the door (#504, ticket 93).
- A door `create` by a member who is not in the project is refused with a sentence that names the project (#490, ticket 167).
- A cancel from a page of another root is refused with 409 (#487, ticket 91).
- A render with new settings no longer rebuilds the page under the hub's lock (#496, ticket 91).
- A commit goes to the root the write went to; `root.git` is no longer fixed at registration (#495, ticket 162).
- The page's check of an action line is a superset of the hub's (#507).
- A kept new-comment draft is matched by a longer lead (#510, ticket 146).
- SPEC section 13 is narrowed to the command line's output; the footer credit stays (#485, ticket 91).
- Attach is offered only for a window whose client and project parts are valid slugs (#502).
- A connection's owner is read from the kernel's socket diagnostics, with `/proc/net/tcp*` as the fallback (#488, ticket 139). The hub then refuses a key or a cookie from another OS user with a 403 that names no uid or path; where owners cannot be read, the check turns itself off and says so (#509, ticket 139).
- The door's `documents` says when a git root gave no answer and when the 10 second budget ran out (#512).
- `sheaf peer add` tells the person to pipe the token into `sheaf peer use` instead of putting it on a command line (#522).

### Fixed

- A page edit keeps the backslashes of the text, writes a shortcode back as the shortcode, and no longer turns a no-break space after a break in a table cell into a lost break; a backslash before a placeholder, a comment or a footnote citation is kept (#475, #479, #482, #517, #524, ticket 137). A backslash in inline math or in a bare URL is kept too (#524), and Enter inside inline code in a table cell keeps the pipe table (#520).
- A save of a document whose owner bits lack read no longer reports a swap that did not happen (#519, ticket 137).
- Five rechecked findings: a name with spaces around it in the door's `create`, a title read that returned a re-read of a cleared cache, a non-text `doc` or `hash` sent to the send door, a page whose meta block is not JSON, and an `incoming` step skipped after a failed unkeep (#525).
- A paste from an online word processor keeps its bold and leaves no backslash paragraphs (#481, ticket 142).
- Enter with the caret in a loose task item moves to the item's text (#476, ticket 144).
- A task line inside code held by a list item is no action (#477, ticket 164).
- A box ticked with another edit in the same save no longer reads shared on an owner-only sheaf (#511).
- The hub does not publish a refresh of a file that moved under the read (#483, ticket 94).
- A frozen leader tab hands the live stream over, and a crashed tab leaves the count when its lock frees (#484, #515, tickets 169, 170).
- A listing abandoned by its caller ends without a BrokenPipeError in the log (#505).
- `openat2` is used only on Linux: its syscall number ended the process with SIGSYS on macOS (#514, ticket 173).

### Tests and tooling

- CI: the browser install is bounded and its leftover `apt-get` ended (#493, #513); pushes to main share one concurrency group (#506); comment fixes (#499).
- Page tests: wait for the Laptops list before Connect (#497); rewrite files whole (#498, ticket 94).

## 1.2.1 (2026-11-20)

Everything merged since 1.2.0 (#465), up to #474.

### Fixed

- Tabs of one browser share one live connection to the hub: the tab holding the Web Lock `sheaf-live`
  owns it and relays over a BroadcastChannel, so a seventh tab no longer waits behind Chrome's limit of
  six connections per host and a comment sent from any tab goes out (#474, ticket 160).
- A box in a list that holds an emoji shortcode such as `:100:` ticks again: the comparison of the
  page against its source ignores the `data-emoji` attribute pandoc adds (#473).
- The phone layout of the Sheaf pane switches on the pane's width, not the screen's:
  `sheaf.css` declares the pane an inline-size container and the layout is a container query at
  600 px and narrower. The tree's cap counts its padding, the table keeps its content height when
  the pane has no height of its own, and the Laptops test measures from the pane's edge (#470,
  findings on #463).

### Tests and tooling

- A test for a pane with no height of its own (#470).

## 1.2.0 (2026-11-19)

Everything merged since 1.1.0 (#424), up to #469.

### Added

- Move a loose page within its root; the old address forwards for ever (#405). Move a loose page to
  another hub (#422, #428, #439); a moved repo's clone sleeps and answers `moved` (#416, #444); a git
  rename that arrives on a pull writes a Forward (#429); Rename folder… in the Sheaf's tree (#442).
- Pages of a repo's clone: a save commits on `dev` or the branch `.sheaf.toml` names, otherwise the
  page is read-only (#407); a save lands only on the branch it was read on (#434); a write to a
  sleeping clone's page wakes the clone first (#438).
- Team comments: store, view and API on the agency hub (#410); the Client and Team tabs of a client
  page, reply, resolve, edit and delete (#447, #449).
- Read-through: a hub reads a client hub's pages and comments through a channel, the Clients folder
  in the Sheaf (#415 and the pull requests that followed it).
- Connect a laptop in the Sheaf: name a laptop, show its connect line once, list and revoke
  laptops (#457).
- Phone layout of the Sheaf pane: a narrow-screen layout at 600 px and narrower, in `sheaf.css` (#463, CSS only).

### Changed

- A listing is cheaper to build: it asks git once per folder, not once per page (#459); reads each
  root's `projects.toml` (#460, #462) and `loose.json` (#466) once per listing; resolves each path once
  (#467); looks for git directories once per folder (#468, 23,939 to 15,790 `lstat` calls per
  mount); and resolves each folder once (#469, 13,239 to 861 `lstat` calls for one Sheaf listing of a
  150-page fixture). These are counts of calls, not CPU measurements.
- Tell drop status: answered ends the drop (#455).
- `peer use` takes its token on stdin and reads a file store from `$CREDENTIALS_DIRECTORY`; its
  messages replace tracebacks (#440, #441, #443).

### Fixed

- The Sheaf data run and the channel read stop when the caller has closed the connection, so an
  abandoned request no longer keeps its worker (#461, #464).
- A forwards file that cannot be written after a trash move is logged, not a 409 (#427); a failed
  landing takes back only its own Write log lines and sends nothing through a redirect
  (#439, #452); Keep and Archive racing a Move leave no mark at the old path (#425).
- A press on the list or the Sheaf before its stylesheet has loaded is no longer lost (#446).
- `Repos.settle()` never joins a thread that is registered and not yet started (#448).

### Tests and tooling

- A test that fails when a tracked file of this public repository holds a name of ours (#445).
- Page tests for the Sheaf's buttons (#426) and a run of flake fixes (#418, #423, #430–#432,
  #435, #436, #450, #453, #454, #456).
