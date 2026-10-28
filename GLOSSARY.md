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
