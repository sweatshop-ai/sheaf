# Map: sheaf as a module of every tiroir, inside Open WebUI

**Type:** wayfinder:map
**Charted:** 2026-11-15 by Frida, with Thierry

## Destination

A spec, ready to hand to whoever builds it, of sheaf as a standard module of every tiroir: each Open WebUI user has their own sheaves there, the way they have their own artifacts, browsed in a Catalog of folders. Thierry's are on tiroir-tt; Marina's would be on tiroir-0. The spec says where a page lives, how an agent session on a laptop gets it there, and what the Catalog looks like.

## Notes

- Why now: on 2026-11-15 a page rendered on the laptop hub loaded forever (open ticket `.scratch/from-render-doc/160-live-streams-use-up-browser-connections.md`, Chrome's six connections per host). Thierry would rather move the pages into a tiroir than keep patching one local hub per laptop.
- Already decided before this map (brain, `claude-memory/thinkingtoo/project_tiroir_prepares_claude_reasons.md`): Open WebUI Notes ruled out as sheaf's home (2026-10-16: ProseMirror JSON, comments dropped, last write wins, no folders); no fork of Open WebUI, sheaf opens inside it through a sidebar entry injected by `/static/loader.js`; proxy mode with Open WebUI as the front already serves the mails root on tiroir-tt (2026-10-27).
- Vocabulary: `GLOSSARY.md`. The **Catalog** (every page a member may open, in folders, no status) is new and is not the **List** (SPEC 9.10, what waits and what is in progress).
- Skills: grilling tickets load `mattpocock-skills:grilling` and `mattpocock-skills:domain-modeling`; research tickets `mattpocock-skills:research`; the prototype ticket `mattpocock-skills:prototype`.
- Write to Thierry in Italian; the tickets and the spec in English.
- Tracker: local markdown, this folder. Frontier = open, unblocked, unclaimed files in `issues/`, first by number.

## Decisions so far

- Destination is a spec, not the build (Thierry, charting, 2026-11-15).
- Every page an agent session renders goes to the tiroir, not only the ones to share (charting).
- The Catalog is new, beside the List; it holds every page, with no status (charting).
- The laptop hub stays as it is; removing it is out of scope (charting).
- Sheaf is per Open WebUI user on each tiroir, like artifacts; Thierry's home is tiroir-tt, Marina's tiroir-0 (charting).
- [What sheaf and Open WebUI run today on tiroir-tt and tiroir-0](issues/01-what-runs-today-on-the-tiroirs.md): tiroir-tt already has proxy mode, all four users as members, a private root for Thierry and a sidebar mount (no Catalog entry); tiroir-0 has Open WebUI and no sheaf module; both serve HTTP/2.
- [Artifacts as the model for a user's own pages](issues/03-artifacts-as-the-model.md): copy private-by-default, stable address, versions with stale writes refused, per-user nested folders shared as a unit; not comments outside the file, chat-bound content or frozen-copy sharing. Open WebUI Notes gained versions and comments since October (still no folders, not markdown-native).
- [A person who works on several tiroirs: where do their pages go](issues/04-one-person-several-tiroirs.md): the root decides, through an optional tiroir in `.sheaf.toml`; otherwise the person's default tiroir (Thierry tiroir-tt, his non-TT pages in his private root there; Marina tiroir-0); same visibility rule everywhere; one Catalog per tiroir; a root moved to another tiroir takes its pages along, old addresses forward (Drive logic).
- [How an agent session on a laptop gets a page onto a tiroir](issues/02-how-a-laptop-agent-reaches-the-tiroir.md): a git root works today (≤ ~60 s lag, line conflicts stop the hub as `push-diverged`, no Tells); the MCP door has create/update with stale writes refused but is loopback-only and the deployed library door lacks create/update; brain-sync-style rsync overwrites page edits; the relay carries Tells only; a remote seat works but moves the agent onto the tiroir.

## Not yet specified

- How long a page lives: Thierry sees most pages as temporary, tied to one session. Archive, expire, or keep forever in the Catalog?
- The name. Thierry dislikes "Sheaf"; "Documents" clashes with all documents in a tiroir; "Notes" is taken by Open WebUI. Candidates from October: proof/épreuve, bon à tirer, desk, drawer.
- What `sheaf FILE.md` does and prints for an agent once the page lives on a tiroir (URL, sign-in, which tiroir).
- Working offline or when the tiroir is down.
- Other members (Sven, Hans on tiroir-tt) and sharing a page between users: SPEC 9.11 visibility exists, its place in the Catalog does not.
- Installing the module on a new tiroir: what the tiroir product ships by default.
- Moving pages between tiroirs: a single page moved against its root's tiroir, and how an old address forwards to another tiroir (ticket 04 decided the Drive logic, not the mechanics).

## Out of scope

- Removing or replacing the laptop hub.
- Fixing ticket 160 (the six-connection limit) on the laptop hub; it is fixed or not on its own.
- A fork of Open WebUI, and Open WebUI Notes as the store (both ruled out 2026-10-16).
