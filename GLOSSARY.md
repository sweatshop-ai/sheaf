# sheaf

A local working page for a markdown document, shared between a person and their agent. The `.md` stays the source; everything done on the page lands back in it.

## Language

**Hub**:
The one local process that serves every document.
_Avoid_: server, per-document server

**Root**:
A git repo (or a folder outside git) whose documents the hub serves, named after its folder.
_Avoid_: project, collection

**Core**:
What every sheaf user gets: rendering, editing, comments, the agent adapter, the plain theme.

**Layer**:
An organisation's additions on top of the core, made of a theme, a root config, and separate programs that use sheaf as a library.
_Avoid_: plugin, extension

**Theme**:
A folder of data that gives pages their look: stylesheet, fonts, wordmark, PDF footer. `plain` is built in.
_Avoid_: skin, brand

**Root config**:
The `.sheaf.toml` file at the top of a root, checked in, that sets the root's theme, its "prepared for" name and its link rule.
_Avoid_: settings, project config

**Share copy**:
A read-only render of a document with every comment removed, for someone outside the conversation.
_Avoid_: client render, client version, public copy

**Copy block**:
A quote whose first line is `[!COPY]`: the page shows it with a Copy button, the Share copy and the PDF as a plain quote (SPEC 6.8).
_Avoid_: callout, snippet

**Share**:
The action a rectoverso's owner ticks to open it to every member whose roots hold it (SPEC 9.11); for a loose page, to every member of the tiroir. Its named form, Share with <members>, opens it to those members only. It never reaches anyone outside the tiroir. It renders nothing and makes no Share copy. Only the owner unticks it, which makes the rectoverso their own alone again. In the list's root a Share moves the rectoverso's file out of its owner's private folder, and unticking it moves the file back; the rectoverso's name, its address, stays.
_Avoid_: publish, unlock

**Client tiroir**:
A hub whose `[proxy]` table says `client = true` (SPEC 9.11). An agent there may Share only with agency members, by name, on `create`, never plain; a plain Share is the member's own act. No role opens another member's page.
_Avoid_: client hub

**Agency member**:
A member whose block says `agency = true`. On a client tiroir, the only members an agent's `Share with` may name.

**Home** (of a rectoverso):
The one path the file of a rectoverso of the list's root lives at, by its visibility: `<client>/<project>/<name>.md` when it is open to the project, `<client>/<project>/private/<short>/<name>.md` when it is its owner's alone (SPEC 9.11). The hub moves the file home; the rectoverso itself is its logical name.
_Avoid_: location, private copy

**Logical name** (of a rectoverso):
`<client>/<project>/<name>.md`, the address of a rectoverso of the list's root wherever its file lives (SPEC 9.11). The hub keys the rectoverso's entry, versions, read state and render settings by it, and finds the file under it only to read or write it. The file's private path is no address.
_Avoid_: private address, physical address

**Link rule**:
The standard that every page, article, tool or document a text names is a link to its URL. It is checked when a page is rendered and told to the agent.

**Diagnostics log**:
The local record of everything that went wrong on a page or the hub, kept for bug reports.
_Avoid_: incident log

**Comment**:
A threaded note a person or an agent leaves on a passage, stored in the `.md` right after that passage. Written as `sheaf-comment`; the older `rd-comment` is read as the same thing.
_Avoid_: annotation, note, marker

**Foreign comment**:
Any HTML comment in the `.md` that sheaf did not write, such as another review tool's comments or a table-of-contents directive. sheaf never changes, moves or drops one, and does not show it as a Comment.

**Hub key**:
The one secret that proves a caller is the person whose hub it is. A browser holds a cookie derived from it, swapped for once; the CLI and the stdio MCP door read it from disk.
_Avoid_: token, edit token, password

**Sign-in nonce**:
A value the hub makes for the key holder that signs one browser in, once, within 30 seconds. `sheaf open` hands the browser this instead of the hub key.
_Avoid_: sign-in token, key URL

**Loopback mode**:
The hub as it runs by default: reached on 127.0.0.1 only, by the hub key, a browser cookie or an MCP token.

**Remote seat**:
A person working on the hub's machine over ssh, with no display there, so a browser on their own machine reaches the hub only through a tunnel. Not proxy mode: the hub is the same, only the way to it differs.
_Avoid_: remote mode, remote host

**Proxy mode**:
The hub served on the origin of another web application, the front, through a reverse proxy on the same machine, with the front's sign-in saying who is asking. Off unless the hub's config switches it on.
_Avoid_: hosted mode, remote mode

**Front**:
The web application whose origin the hub's pages share in proxy mode, and whose sign-in says who the member is.
_Avoid_: host app, parent app

**Verifier**:
The small service the reverse proxy asks, in proxy mode, whether a request carries a session of the front, and which member it is. Not part of the hub.

**Member**:
A user of the front whom the hub's config lets in through proxy mode, with the roots they see and the name they sign with. A member has no account on the machine.
_Avoid_: account, login

**Owner** (of a rectoverso):
The member a rectoverso belongs to: the assignee of its issue in the list's record, else the member its front matter's `owner` names (SPEC 9.11). Only the owner reads a rectoverso that is its owner's alone, and only the owner ticks Share. A member's roots are not "owned": a root is one a member may open (9.9), whatever the code's `owns` says.
_Avoid_: author, creator, root owner

**Visibility**:
Whether a rectoverso is open to every member whose roots hold it, or its owner's alone, as the hub reads it from the front matter (SPEC 9.11).
_Avoid_: permission, privacy, ACL

**List**:
A member's page of the rectoversos that wait on someone and the ones in progress, grouped by client and project, their status taken from their issues (SPEC 9.10). It shows only rectoversos with work on them.
_Avoid_: catalog, index, dashboard

**Sheaf** (of a member):
A member's browsable tree of folders holding every rectoverso they may open, with or without an issue, and no status; also the product a member reads, tiroir Sheaf, and its sidebar entry. A folder is where the rectoverso lives: its root, then the root's sub-folders; those another member Shared sit apart, under their owner. Not the List: the List says what waits, the Sheaf says where a rectoverso is. The engine and the laptop command carry the same name. (Named the Catalog 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 06; renamed the Sheaf by the maintainer during ticket 19; built in #387; Shared rectoversos in #394.)
_Avoid_: Catalog, list, library, documents

**Rectoverso**:
One page as a member reads it: a sheet with two sides, the recto the agent writes and the verso where the member answers. What `sheaf FILE.md` sends and what a row of the Sheaf opens. One word, the same in every language, so dictation keeps it. (Named 2026-11-15 by the maintainer during wayfinder `sheaf-in-open-webui` ticket 19, replacing ticket 15's product name Recto; built in #384, #387 and #397.)
_Avoid_: Recto, a sheaf (for one page), document, note

**Verso**:
The side of a page that holds its Comments, as a member reads it: the agent writes the recto of a rectoverso, the member answers on its verso. A word for the place, not for one comment. (Named 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 15; the word is in the code since #384; Team comments, the agency's own verso, built in #410.)
_Avoid_: back, thread panel

**Root's tiroir**:
The tiroir every page of a root goes to, named in its root config; a root that names none sends its pages to the person's default tiroir. A root moved to another tiroir takes its pages with it, versions and comments, and their old addresses lead to the new ones. (Decided 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 04; partly built: a root's `tiroir` is read by `sheaf FILE.md` since #397, and the pieces of a root's move (the notice, the check, `send_root`, `check_root`, the sleeping clone) are in #416 and #428, but nothing calls them yet, so a root does not move; a loose page's old address forwards since #411 and #422.)
Built for the receiving end: a moved root's pages land on the tiroir its `.sheaf.toml` names, each whole or not at all, by the channel's `root` verb (SPEC 9.9); the sending end runs in the archive sweep (`root_sender`): it sends the pages the hub keeps something of, writes a Forward per confirmed page and then puts the clone to sleep.
_Avoid_: binding, target

**Client tiroir**:
A tiroir that belongs to a client of the agency and holds only what is client-facing. Its users' brains, chats and private pages are theirs alone: no agent and no member of the agency reads them. The agency's members on it are members like any other, never its administrators. (Decided 2026-11-16, wayfinder `sheaf-in-open-webui` ticket 22; partly built: the hub's rules in #404, Read-through in #415, Team comments in #410; the accounts on a client tiroir are not built.)

**Read-through**:
How the agency's tiroir shows a client tiroir's pages: its "Clients" folder asks the client tiroir, over the hub-to-hub channel, for what the signed-in agency member may open there, and shows the answer without keeping any of it. The client tiroir does all the judging, as that member. (Decided 2026-11-16, wayfinder `sheaf-in-open-webui` ticket 23.)
_Avoid_: mirror, sync, copy

**Team comment**:
A comment the agency's members leave on a client tiroir's rectoverso that the client never sees. It lives on the agency's tiroir, tied to the rectoverso's address, on a team verso beside the client's; it never reaches the client tiroir. It is built: the store, its view and API on the agency hub, and the hook-up to a client page (the `team` list beside `comments`, a `side` on every add).
_Avoid_: internal comment, private comment, team note

**Default tiroir** (of a person):
The one tiroir a person's pages go to when their root names none: Alice's is the agency tiroir, Dave's a client tiroir. Each tiroir has its own Sheaf per member; there is no Sheaf across tiroirs, except that the agency's tiroir shows the client tiroirs' rectoversos its members may open. (Decided 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 04; the exception 2026-11-16, ticket 22; built in #397, #387 and #415.)
_Avoid_: home tiroir (a rectoverso's home is a path)

**Loose page**:
A page in no git repo: a session's scratchpad, a temporary folder, or anything a chat client such as Claude.ai or ChatGPT makes. Its original lives on the tiroir; a page in a git repo has git as its original. (Decided 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 05; built in #386 and #397.)
_Avoid_: scratch page, orphan page

**Loose root** (of a member):
The one folder, `loose-<short>`, where a member's Loose pages are written, made on the member's first door `create` with no root. It is kept against the member's id, so a rename or a short name another member held never gives or takes it. A page marked Keep (stored in the root's `.sheaf/`, not in the text) is never archived.
_Avoid_: scratch folder, loose folder

**Repo clone** (on a tiroir):
The tiroir's own copy of a git repo that a member's page came from, made the first time a page of that repo is rendered for that tiroir. One per repo per tiroir, whoever's pages it holds; it holds the folders with pages only. A page in it is still its member's alone until Shared. (Decided 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 14; built in #400, #434 and #438.)
_Avoid_: mirror, checkout

**Archived page**:
A loose page out of the Sheaf's default view, after `archive_after` days with no write, no comment and no open comment, or by the member's hand (Archive now). It still opens at its address and comes back when written or commented, or Restored. Not deleted: only the member deletes a page.
_Avoid_: expired, stale

**Kept page**:
A loose page the member marked Keep (or made with `keep`): never archived, however quiet. The same control turns it off.
_Avoid_: pinned, protected

**Trash**:
The root's `.sheaf/trash/`, where a page the member deleted waits thirty days to be restored, then is gone. Only the member's own act from the Sheaf puts a page there; no agent or door path does.
_Avoid_: bin, recycle bin

**Laptop token**:
The agent token that "Connect a laptop" makes for one laptop of one member. It signs as `Claude Code (<member>)` whichever laptop it is, is checked by the hub on every request, sees what its member sees, and is revoked by the laptop's name. `sheaf connect` puts it in the laptop's login keyring and in Claude Code's MCP entries. (Decided 2026-11-16, wayfinder `sheaf-in-open-webui` ticket 05; the Sheaf's page for it comes with the Sheaf view.)
_Avoid_: device key, API key

**Write log**:
The hub's own record of the writes to its pages, one line per write whatever the path: who wrote, from which place (laptop, chat client, tiroir, page), and the agent session when it is known. It is where a row of the Sheaf gets its last write and its last agent session. Not the Diagnostics log, which records what went wrong. (Decided 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 09; built in #385.)
_Avoid_: journal, history, audit log

**Stop James**:
The action any member ticks on a rectoverso of the assistant James to end his work on its project (SPEC 9.11). It is the one place the core names a deployment's assistant: the hub writes a diagnostics row and, with `[list] stop_dir`, a file the deployment's supervisor reads; stopping is the deployment's, a Layer concern the core only signals.

**Belongs to**:
The action that answers what an unsure thread belongs to: one box per candidate, `- [ ] Belongs to <slug> (ref <thread>)`, the one word with a slug and a thread (SPEC 9.10; Merge, Deploy and Install take the rest of the line). The slug names whatever the thread belongs to, a client, a project or a team. The boxes are the options of one answer: on the list each is a one-off button named by its slug, and once one is ticked the others are no actions and the hub refuses a second tick (#109); the deployment's mail module moves the thread. (Renamed from Move to by the maintainer, 2026-11-15, wayfinder `sheaf-in-open-webui` ticket 20.)
_Avoid_: Move to, reassign, client, transfer

**Move** (of a rectoverso):
The owner putting a loose rectoverso in another folder of its root, from the Sheaf or by their agent; renaming a folder moves each rectoverso in it. A loose rectoverso can also move to another tiroir where its owner has an account; it stays the owner's and arrives as theirs alone, its Share left behind. A repo rectoverso is moved by git, not from the Sheaf, and goes to another tiroir only with its whole root. The old address forwards to the new one. A folder exists only while a rectoverso is in it. (Decided 2026-11-15, wayfinder `sheaf-in-open-webui` tickets 20 and 21; built in #405 within a root, #411 and #422 to another tiroir; a root's move is partly built, see Root's tiroir.)
Built for a loose rectoverso within its root (SPEC 9.11) and to another tiroir.
_Avoid_: Move to, refile, rename

**Forward** (of an address):
The hub's record that an old address of a rectoverso now leads to its new one, after a Move, a git rename or a move to another tiroir. It never expires; links that name the old address are not rewritten. Across tiroirs it leads only someone who can sign in to the new one; an agent at the old address is told where the rectoverso went and what to do. (Decided 2026-11-15, wayfinder `sheaf-in-open-webui` tickets 20 and 21; built in #405, #429, #411 and #422.)
Built for a Move within a root (SPEC 9.11), a git rename and a move to another tiroir: the rectoverso's owner is led by it, no one else; a stranger is answered as for an address never used.
_Avoid_: redirect, alias

**One-off action**:
An action a member presses once and that stays pressed: every word but Share (SPEC 9.10), and the merge desk's Merge, Deploy and Install (action-buttons 04). On the list it is a red button; on a page it is a red button where its line is, inside the text, with the rest of the line beside it as its text (action-buttons 01); a one-off whose box the page does not find is in the row above the document. It reads Undo for 5 seconds before the hub writes the tick; once pressed it stays on the row, filled and locked, with who pressed it and when (#110); the hub refuses a save that unticks it (#108); a Belongs to is a one-off too, one button per candidate.
_Avoid_: single-use, final

**Pressed box**:
A ticked box of an action's word, `- [x] Approve` (SPEC 9.10). On the list and on the rectoverso's page a pressed one-off is a locked button that says who pressed it and when, from the commit that last changed its line (#110); a pressed toggle is one its owner may release.
_Avoid_: done box, checked action

**Tick box**:
A task line's box that is switched on and off, `- [ ] Approved: the quote of 12 November`, drawn as a checkbox; its label ticks it too (action-buttons 02).
_Avoid_: toggle (for the drawing), checkmark

**Label**:
The words of a tick box's line that belong to the box: those before the first `:` or ` — `, else the first word. A click on them ticks or unticks the box; the rest of the line is ordinary text, to select and comment on.
_Avoid_: caption, title

**Toggle action**:
An action a member presses and may release again; today only Share (SPEC 9.10, 9.11), and a tick box on a page (action-buttons 03): something switched on and off is a tick box, something launched once is a button (the maintainer, 2026-11-13). On the page its line is a checkbox, `- [ ] Shared with the team` (`- [ ] Share` is read as before), ticked and unticked at once by the box or its label, the whole line, by the rectoverso's owner alone (9.11, 10.11); on the list it stays a blue button with `aria-pressed` (#110).
_Avoid_: switch

**Pointer** (of a rectoverso):
What a rectoverso becomes once its thread moved to another client: its front matter, with `moved_to:` naming the new path, and one line. It keeps its `issue` and its versions, and is never a row on the list (SPEC 9.10).
_Avoid_: redirect, stub, tombstone

**Work on this**:
What a member does with a rectoverso's agent session from its page (SPEC 9.12): attach to James's window on the box, if they have a shell there, or fork the live session to their own machine with `tiroir work`. The page offers it from the meta block's `work`.
_Avoid_: resume, take over, hand over

**Fork** (of a session):
A new session on a member's machine, started from the transcript of a rectoverso's box-hosted session, which the hub serves and never changes (SPEC 9.12). Reported to the hub, it becomes the first of the rectoverso's `sessions`, under the signed-in member's name; the session it came from goes on as it was.
_Avoid_: copy, clone, move

**Box-hosted session**:
A rectoverso's session whose `host` in its `sessions` front matter is `[list] box`: James's, on the deployment's box (SPEC 9.12). The hub serves the transcript of no other session, and only when one is the live session, the first item, do Tells go to James's window by a file in `[list] tell_dir`.
_Avoid_: remote session, server session

**Agent adapter**:
How the hub reaches an agent session: ask it a question, deliver a Tell, read its state, stop it. Each agent offers only what it can really do.

**MCP door**:
How an agent reaches the hub: read a document's threads and its text, reply, resolve, and, with the right to write, make a page and change its text. Any agent that speaks MCP can use it, whether the hub runs on the same machine or on a box it connects to.
_Avoid_: MCP server, plugin

**Agent**:
One AI client acting for one member: `ChatGPT (Bob)`, `Claude (Bob)`, `tiroir (Bob)`. It reaches the hub through the MCP door with its own MCP token, sees only that member's roots, signs its replies `Client (Member)`, and can be the target of a Tell. `tiroir` names the assistant inside Open WebUI only; ChatGPT reaching the hub through the tiroir connector is still `ChatGPT`.
_Avoid_: bot, assistant, integration

**MCP token**:
A named, revocable secret that lets one agent use the hub's HTTP MCP door, and nothing else. A token made with `--write` may also read, make and change pages through the door.
_Avoid_: API key, hub key

**Target**:
Who a document's Tell reaches: the last agent session or agent that worked on it, which the page names and lets the person change.
_Avoid_: target session (when the target is an agent)

**Tell**:
A comment that asks the target to act. Delivered into a running agent session when there is one to reach; for an agent that nothing can reach from outside (ChatGPT, Claude.ai), it waits on the document until that agent next asks what waits for it, with no expiry, and the person can cancel it from the page. Either way the target acts and replies in the thread.
_Avoid_: send, push

**Role**:
What a reply is, recorded apart from who wrote it: `answer` for a reply that changed nothing, `action` for what the target did after a Tell.
_Avoid_: reply type, magic author name

**Ask** (retired):
A question answered by a fork of the target session without changing anything. Retired in 2026-11: unused, and impossible for an agent that has no session to fork. Replies it left keep their role `answer`.

**Pin**:
A version of a document that the hub keeps beside the newest because a page holds its reload on it (`POST /_/pin`), so what the page sends later against that version is still taken. It is not the popover a page fixes on screen.
_Avoid_: lock, snapshot

**Versions store**:
Where the hub keeps the texts it handed pages, per document, so a save against an older one is merged: the state folder's `versions/`, or with `versions = "root"` the root's own `.sheaf/versions/`, committed with the document in a root that commits.
_Avoid_: history, backup, snapshots

**Dictation**:
Text spoken into the microphone button of a chat box and transcribed: it is put in the field at the cursor and stays editable. It is never sent to the agent by itself, and the sound is not kept.
_Avoid_: voice message, speech-to-text send

**Shared with me**:
The top-level folder of a member's Sheaf that holds the loose pages other members Shared with them, one sub-folder per owner. It tells nothing of the owner's own folders. A row in it is `new` until the member opens the page, and again when the page changed since. See SPEC 9.11, "Share on a loose page".
_Avoid_: inbox, received
