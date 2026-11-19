# Changelog

sheafmd is released by merging a pull request that sets `__version__` in `src/sheafmd/__init__.py`.
Its page assets are cached by version (`/_/mount.css?v=<version>`, immutable), so the version
changes whenever an asset does. The entries name pull requests of sweatshop-ai/sheaf.

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
