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

**Share**:
The action a sheaf's owner ticks to open it to every member whose roots hold it (SPEC 9.11). It renders nothing and makes no Share copy. Only the owner unticks it, which makes the sheaf their own alone again. In the list's root a Share moves the sheaf's file out of its owner's private folder, and unticking it moves the file back; the sheaf's name, its address, stays.
_Avoid_: publish, unlock

**Home** (of a sheaf):
The one path the file of a sheaf of the list's root lives at, by its visibility: `<client>/<project>/<name>.md` when it is open to the project, `<client>/<project>/private/<short>/<name>.md` when it is its owner's alone (SPEC 9.11). The hub moves the file home; the sheaf itself is its logical name.
_Avoid_: location, private copy

**Logical name** (of a sheaf):
`<client>/<project>/<name>.md`, the address of a sheaf of the list's root wherever its file lives (SPEC 9.11). The hub keys the sheaf's entry, versions, read state and render settings by it, and finds the file under it only to read or write it. The file's private path is no address.
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

**Owner** (of a sheaf):
The member a sheaf belongs to: the assignee of its issue in the list's record, else the member its front matter's `owner` names (SPEC 9.11). Only the owner reads a sheaf that is its owner's alone, and only the owner ticks Share. A member's roots are not "owned": a root is one a member may open (9.9), whatever the code's `owns` says.
_Avoid_: author, creator, root owner

**Visibility**:
Whether a sheaf is open to every member whose roots hold it, or its owner's alone, as the hub reads it from the front matter (SPEC 9.11).
_Avoid_: permission, privacy, ACL

**Stop James**:
The action any member ticks on a sheaf of the assistant James to end his work on its project (SPEC 9.11). It is the one place the core names a deployment's assistant: the hub writes a diagnostics row and, with `[list] stop_dir`, a file the deployment's supervisor reads; stopping is the deployment's, a Layer concern the core only signals.

**Move to**:
The action that answers which client an unsure thread is for: one box per candidate, `- [ ] Move to <slug> (ref <thread>)`, the only word that takes an argument (SPEC 9.10). The boxes are the options of one answer: on the list each is a one-off button named by its slug, and once one is ticked the others are no actions and the hub refuses a second tick (#109); the deployment's mail module moves the thread.
_Avoid_: reassign, transfer

**One-off action**:
An action a member presses once and that stays pressed: every word but Share (SPEC 9.10). On the list it is a red button that reads Undo for 5 seconds before the hub writes the tick; once pressed it stays on the row, filled and locked, with who pressed it and when (#110); the hub refuses a save that unticks it (#108); a Move to is a one-off too, one button per candidate.
_Avoid_: single-use, final

**Toggle action**:
An action a member presses and may release again; today only Share (SPEC 9.10, 9.11). On the list it is a blue button with `aria-pressed`, pressed and released there, or in the sheaf, by the sheaf's owner (#110).
_Avoid_: switch

**Pointer** (of a sheaf):
What a sheaf becomes once its thread moved to another client: its front matter, with `moved_to:` naming the new path, and one line. It keeps its `issue` and its versions, and is never a row on the list (SPEC 9.10).
_Avoid_: redirect, stub, tombstone

**Work on this**:
What a member does with a sheaf's agent session from its page (SPEC 9.12): attach to James's window on the box, if they have a shell there, or fork the live session to their own machine with `tiroir work`. The page offers it from the meta block's `work`.
_Avoid_: resume, take over, hand over

**Fork** (of a session):
A new session on a member's machine, started from the transcript of a sheaf's box-hosted session, which the hub serves and never changes (SPEC 9.12). Reported to the hub, it becomes the first of the sheaf's `sessions`, under the signed-in member's name; the session it came from goes on as it was.
_Avoid_: copy, clone, move

**Box-hosted session**:
A sheaf's session whose `host` in its `sessions` front matter is `[list] box`: James's, on the deployment's box (SPEC 9.12). The hub serves the transcript of no other session, and only when one is the live session, the first item, do Ask and Tell go to James's window by a file in `[list] tell_dir`.
_Avoid_: remote session, server session

**Agent adapter**:
How the hub reaches an agent session: ask it a question, deliver a Tell, read its state, stop it. Each agent offers only what it can really do.

**MCP door**:
How an agent reaches the hub: read a document's threads and its text, reply, resolve, and, with the right to write, make a page and change its text. Any agent that speaks MCP can use it, whether the hub runs on the same machine or on a box it connects to.
_Avoid_: MCP server, plugin

**MCP token**:
A named, revocable secret that lets one agent use the hub's HTTP MCP door, and nothing else. A token made with `--write` may also read, make and change pages through the door.
_Avoid_: API key, hub key

**Target session**:
The agent session a document's Ask and Tell reach: the last one that rendered it from an agent.

**Ask**:
A question on a comment thread, answered in the thread by a fork of the target session, which changes nothing.

**Tell**:
A comment sent into the running target session, which acts on it and replies in the thread.
_Avoid_: send, push

**Role**:
What a reply is, recorded apart from who wrote it: `answer` for an Ask, `action` for what a session did after a Tell.
_Avoid_: reply type, magic author name

**Pin**:
A version of a document that the hub keeps beside the newest because a page holds its reload on it (`POST /_/pin`), so what the page sends later against that version is still taken. It is not the popover a page fixes on screen.
_Avoid_: lock, snapshot

**Versions store**:
Where the hub keeps the texts it handed pages, per document, so a save against an older one is merged: the state folder's `versions/`, or with `versions = "root"` the root's own `.sheaf/versions/`, committed with the document in a root that commits.
_Avoid_: history, backup, snapshots
