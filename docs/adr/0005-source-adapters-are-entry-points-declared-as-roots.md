# Source adapters are entry points, declared as roots in the user config

Status: accepted (2026-11-24, block-editor design, decision 09)

The block editor, the source-adapter interface (ADR 0004) and the Markdown-file adapter live **inside sheaf**, as the subpackage `sheafmd/blocks/`, with the interface as the module boundary. Every other source adapter lives in a package of its own and is found by the hub through the Python entry-point group `sheaf.adapters`. A source other than a folder is declared in the user config (`config.toml`) as a `[sources.<name>]` table, and the hub serves it as a root. The reason is that the block tree, the versions store, the page and the MCP tools on blocks are all sheaf's, so the interface has a single consumer today; while adapters belong to whoever owns the source they write to, and a source bound to one organisation's site cannot live in a public package.

## Where each part lives

- **In sheaf:** block tree and block operations (core), the adapter interface, the Markdown-file adapter, the TipTap page and its bundle, the MCP tools on blocks. They move to a separate package only when a second program needs them.
- **A generic adapter** (a WordPress REST adapter, an adapter for an Astro site's content in any git repo) is a public package of its own that registers under `sheaf.adapters`.
- **An adapter bound to one organisation's site** lives in that organisation's private repository, beside the code that already writes to that site, and registers the same way. It is part of that organisation's layer.

## Enabling an adapter

- Every folder root keeps the Markdown-file adapter by default; nothing is configured.
- A source with no local folder is a `[sources.<name>]` table in `config.toml`: the adapter's entry-point name, its settings, and the path to a secrets file readable by the hub's account only. The hub registers it as a root named `<name>`; a rectoverso's path inside it is the adapter's own document name.
- `.sheaf.toml` does not name an adapter: it is checked in, sits in a folder, and must never hold or point at credentials.
- On a machine set up by a deployment stage, the stage writes the table.

## Interface version

sheaf carries an adapter-interface version, an integer. Each adapter declares the version it implements. At start the hub refuses an adapter of another version: it prints and logs an error naming both versions, and that root is not served; other roots are unaffected (fail closed).

## The TipTap bundle

The TipTap sources, `package.json` and the lockfile live in the sheaf repository. A pinned esbuild builds the bundle; the built file is committed and shipped in the wheel, so installing sheaf needs no Node. CI builds it again and fails when the committed file differs. This settles what ADR 0003 left to implementation.

## Open

Whether an adapter runs inside the hub process or behind a service it calls is not decided here. It depends on where the hub runs for a shared site (on the shared machine, on a laptop connected to it) and is a later decision.

## Considered options

- **A separate editor package that sheaf depends on.** Rejected: with sheaf as its only consumer, the package boundary would be a seam with one side, released twice.
- **Only the interface in a tiny separate package**, so adapters depend on it alone. Rejected for now: the interface version gives adapters the same protection without a third package.
- **Every adapter inside sheaf, enabled by config.** Rejected: an adapter bound to one organisation's site, with its repository and branch as constants, cannot go into a public package.
- **The adapter named in `.sheaf.toml`.** Rejected: a non-file source has no folder to hold the file, and the file is checked in.
- **A CLI command registering the source in `roots.json`.** Rejected: settings and the secrets path would live in a state file nobody reads; the user config is where a machine's setup is written.
- **No interface version, a sheaf version range in the adapter's metadata.** Rejected: pip resolves ranges at install, but an adapter installed beside a newer sheaf would fail at its first write instead of at start.
- **TipTap built only in CI, or upstream files vendored without a build.** Rejected: the first makes a source checkout need Node to show a page; the second ships unminified modules with no check of what they are.

## Consequences

- `Root` covers a non-folder source; the hub's keys (`<root>/<path>`), `roots.json` and a member's Sheaf tree work for it unchanged.
- The `.md` suffix checks (ADR 0004) give way to the adapter's own document names once a second adapter exists.
- The design of an adapter that writes to someone else's site is read by that site's owner before it is built.
