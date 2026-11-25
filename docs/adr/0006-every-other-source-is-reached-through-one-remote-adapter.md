# Every source other than a Markdown file is reached through one remote adapter

Status: accepted (2026-11-25, block-editor design, decision 13). Amends ADR 0005.

sheaf has two source adapters and no plug-in mechanism: the **Markdown-file adapter** for folder roots, and one generic **remote adapter** that speaks a small HTTP protocol to a **source service**, a program the source's owner runs beside the source. The source service holds the source's credentials, maps its own format to the block tree, checks its own rules and maps members to commit authors; the hub holds one bearer per source and never a key to the site. The reason is that a hub reachable from the front's origin and from laptop tokens is the wrong place for a key that can change someone's website, and that a site already written by its owner's tools keeps one key and one set of checks only when sheaf goes through those tools instead of beside them.

## Where a source is served

A source root is served only by the hub of the tiroir that owns the source. A laptop works on that source's pages through the tiroir's hub, as on any other page there (`sheaf connect`); a laptop's own hub never declares a source and never holds its credentials.

## What ADR 0005 keeps and loses

- **Kept:** the editor, the interface and the Markdown-file adapter inside sheaf (`sheafmd/blocks/`); the committed TipTap bundle; a non-folder source declared as `[sources.<name>]` in `config.toml` and served as a root; the integer interface version, checked at start and failing closed.
- **Withdrawn:** the entry-point group `sheaf.adapters`. No adapter is loaded into the hub process. A `[sources.<name>]` table names the service's URL (HTTPS, or a Unix socket on the same machine) and the path of a secrets file, readable by the hub's account only, that holds the hub's bearer for that service.
- **Changed in meaning:** a generic adapter (WordPress, an Astro site in any git repository) is a source service, public or not; a WordPress site can be its own source service as a WordPress plugin. A source service bound to one organisation's site lives in that organisation's private repository, beside the code that already writes to the site.

## The protocol

JSON over HTTP, versioned by the interface integer. Every request carries the hub's bearer.

- `info`: the interface version the service implements and the source's display name. Called at hub start.
- `documents`: the documents the hub may list in the root, each with its name.
- `read(document)`: the block tree of ADR 0004 and the opaque base.
- `write(document, blocks, base, author, note)`: one of the outcomes of ADR 0004, `written` (new base, new ids), `conflict` (the changed blocks) or `refused` (reason and block).
- `publish(document, note)`: only when the service declares it.

The block tree is ADR 0004's, serialised: per block its id, Block type, declared attributes, capabilities and content, with containers holding children; a block's content is inline Markdown in the wire form of ADR 0001. sheaf never parses the source's own format.

## Who writes

The hub states the member it signed in (the front's session, or the member a token belongs to) as `author` on every write. The service trusts that statement because only the hub holds the bearer. The service maps the member to the name and address of a commit, or the source's equivalent, from its own configuration, and refuses a member it has no mapping for. A write made with an agent's token is its member's; the note says `via <token name>`.

## When the service is unreachable or of another version

- **Another interface version** reported by `info`: the root is refused until the hub restarts, its error names both versions, and nothing is queued. Other roots are unaffected.
- **Unreachable:** the hub keeps the last read of each document of a remote source in its state. During an outage a document already read opens from that copy, with a notice that the source cannot be reached and that changes are kept on the hub; a document never read cannot be opened. Writes go to a queue in the hub's state that survives a restart. Consecutive writes to one document by the same member collapse into the latest tree on the oldest base; writes by different members stay separate, in order, so every commit names its real author.
- **Delivery:** when the service answers again, each queued write is sent. ADR 0004's rule runs first: with a stale base and every targeted block unchanged, core applies the write to the current version. Otherwise a conflict becomes the existing block merge with conflict comments on the page, its author gets a Tell, and the entry stays queued until the author resolves it; a refusal is reported the same way with its reason. Nothing queued is dropped, and queued writes have no expiry. A write still queued after 24 hours raises one entry in the hub's diagnostics.

## Considered options

- **In-process adapters only, each holding or fetching its own credential** (ADR 0005 as written). Rejected: a site key would sit in the hub's process, and a site already written by its owner's service would have two keys and two sets of checks.
- **In-process adapters that may call a service of their own choosing.** Rejected: every adapter would invent its own client and its own trust between hub and service; one protocol defined once costs less than many.
- **Both entry points and the remote adapter.** Rejected: with an in-process way still open, nothing stops a site key from entering the hub.
- **Whole Markdown documents on the wire.** Rejected for the reason ADR 0004 gives: a YAML or CMS source would invent Markdown, and ids and capabilities would have nowhere to live.
- **MCP tools as the protocol.** Rejected: MCP is built for agents; a service that serves each member on a listener of their own would make the hub hold every member's credential.
- **Refusing writes while the service is down.** Rejected: an outage of the site's service would stop every member's work on its pages.
- **Last write wins on delivery, or queued writes that expire.** Rejected: the first silently undoes a change made during the outage, the second loses work when an outage outlasts the limit.

## Consequences

- The hub gains per-source state: a cache of last reads and a durable write queue.
- The `.md` suffix checks (ADR 0004) give way once the remote adapter exists, as ADR 0005 foresaw.
- Comments on a remote source's blocks use the hub-side store ADR 0004 describes.
- A source service is written, reviewed and deployed by the source's owner; sheaf ships only the client and the protocol's documentation.
