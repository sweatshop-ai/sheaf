# Source service protocol: interface version 1

A Source service is a program the owner of a source runs beside it. A hub reaches it through the remote adapter (ADR 0006) and
serves the source as a root. `python -m sheafmd.sourceservice` is the reference service: a folder of Markdown, and the template for
a service of another source.

## Transport

- JSON over HTTPS, or over a Unix socket (`unix:///absolute/path.sock`). Plain `http://` is accepted for a loopback address only.
- Every call is `POST /<call>` with `Authorization: Bearer <the hub's bearer>` and a JSON object as the body.
- A request without the bearer, or with another, is answered `unauthorized` with `Connection: close`, and its body is not used.
- The hub holds the one bearer, in a file only its account can read. It holds no key to the site: the service does.
- Timeouts on the hub's side: 5 s to connect, 30 s for a request.

## Calls

| Call | Request | Answer |
|---|---|---|
| `info` | `{"interface": 1}` | `{"interface": 1, "name": text, "publish": bool}` |
| `documents` | `{"cursor": text}` (absent for the first page) | `{"documents": [{"name": text}], "next": cursor or null}`, at most 500 a page |
| `read` | `{"document": name}` | `{"tree": {"text": text}, "base": text}` |
| `write` | `{"document": name, "tree": {"text": text}, "base": text, "author": member, "note": text}` | an outcome |
| `publish` | `{"document": name, "note": text}` | only where `info` says `publish` |

A write answers one of three outcomes: `written` with the new `base`, `conflict` with the current `base`, or `refused` with a `reason`.
The `base` is the hash of the text read. The cursor is opaque: it is passed back as it was given.

## Errors

An error is `{"error": {"code": text, "message": text}}`.

| Code | HTTP | Meaning |
|---|---|---|
| `unauthorized` | 401 | the bearer is missing or wrong |
| `not_found` | 404 | no such document |
| `bad_request` | 400 | the request is not one the service understands |
| `unknown_author` | 403 | the member who wrote has no author in the service's table |
| `version` | 409 | the service speaks another interface version |
| `unavailable` | 503 | the service cannot answer now |

`unknown_author` is an ordinary answer: the hub shows the write as `refused`. A service that reports another `interface` than the
hub speaks is left unserved by the hub, with an error that names both versions; the hub's other roots keep serving.

## Authors

The service keeps a small table from member to commit author, and refuses a member it does not name before it reads or writes
anything. The reference service reads it from a TOML file:

    [authors]
    "Ada Lovelace" = "Ada Lovelace <ada@example.org>"

A write made through an agent token carries `via <token name>` at the end of its note.

## The hub

    [sources.shop]
    url = "unix:///run/shop/sheaf.sock"
    secrets = "/etc/sheaf/shop.bearer"
    theme = "/etc/sheaf/themes/shop"

A source takes `url`, `secrets` and `theme`, and no other key. The secrets file holds the bearer alone, on one line, belongs to the
hub's account and has no group or other permission. A page of the source is `/<name>/<document>`; it opens read-only in the
rectoverso with the Theme the source names (a built-in name or an absolute folder: the source has no folder to resolve a relative one against). Only a tiroir's hub serves a source.

## Who may read a source

A source is a member's only when the member's table names it: `sources = ["shop"]` in `[proxy.members."<id>"]`, next to `roots`.
A member whose table does not name it is answered "no such root", as for a folder that is not theirs. A folder root that holds the
name of a declared source keeps it, and the source stays unserved.

## What the reference service assumes

The reference service owns its folder and its repository: a single writer, with no concurrent local edits and no Git operation
running beside it, and the root not replaced while it runs. It is a reference implementation and the contract suite's partner,
not hardened for a shared working copy. It enforces what it can: the root is opened once at start and every path is opened from
that descriptor without following links; one lock covers a write from the look at the file to the end of the commit; it refuses to
start, and answers each write `unavailable`, while a merge, rebase, cherry-pick or revert is in progress or the index holds staged
changes. A write replaces the file by atomic rename and commits it with Git's own filters and ignore rules. If `git add` fails cleanly the previous bytes are put back and the write is `refused`; if `git add` times out or the rollback fails, or `git commit` fails in any way, the service stops (see Failure).

The hub trusts a configured service with its own documents: names, cursors and document text are passed on unchanged, and only the
service's words (an error message, a refusal's `reason`) are redacted of the bearer.

## Failure

The reference service stops rather than guess, except a `git add` that fails cleanly, with the previous bytes put back: that stays an ordinary `refused`, the document as it was. When `git commit`, or a Git step after the file was replaced, fails, times out or cannot
be run, or the rollback of a failed `git add` fails, the service has stopped: the write is answered `unavailable` (never `written`, never
`refused`), it changes nothing further, and every later read, write and listing is answered `unavailable`. It logs HEAD before the
write, HEAD now and the path.



Do not restart it. The stop is also written to a marker, `<git-dir>/sheaf-source-stopped`, with the time, the path, HEAD before and HEAD now. It
lies inside the git dir, so it is never listed or served, and the service does not start while it exists. Inspect the repository with
Git, starting from `git status` and the logged HEADs, and repair it by hand, keeping any operator edits in both the working file and the
index. Then remove the marker and restart.

At startup the service refuses only in these cases: the marker exists; an index lock exists; a merge, rebase, cherry-pick, revert or
sequencer operation is in progress; changes are staged; `git status` exits with an error; or a `.git` exists that Git cannot read.
Ignored, untracked and unstaged files do not affect a start. The refusal names this section.
