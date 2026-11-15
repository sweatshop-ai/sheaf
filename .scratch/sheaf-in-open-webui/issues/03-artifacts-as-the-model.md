# 03: Artifacts as the model for a user's own pages

**Type:** research
**Status:** resolved
**Blocked by:** none
**Map:** ../map.md

## Question

Thierry pictures a user's sheaves like their artifacts. How do Claude (claude.ai artifacts) and Open WebUI (its artifacts, notes, knowledge, folders) tie a piece of content to one user: where it is listed, how it is grouped, how it is shared, how long it lives, what an agent can create or update? Which of those behaviours should a user's sheaves copy, and which do not fit a markdown file with comments that an agent keeps editing?

## Answer

Resolved 2026-11-15 by a research subagent of Frida. Full findings: `.scratch/sheaf-in-open-webui/research/03-artifacts-as-model.md` on branch `research/03-artifacts-as-model` (commit 3fb645d, pushed). Sources: Anthropic artifacts docs and Help Center as served 2026-11-15; Open WebUI source at v0.13.3 (b0e6098).

- **claude.ai artifacts:** private to the owner first; listed most recent first; pins are personal; folders only on Team/Enterprise, as a way to share; share by link, people, org or folder with view/comment/edit; every publish is a version and a stale publish is refused; lives until deleted or an org retention period ends.
- **Open WebUI artifacts** are code blocks inside a chat message: no store of their own, they live and are shared as their chat.
- **Open WebUI chat folders:** nested, per user, chats only, shareable read or write; a shared chat is a frozen copy; nothing expires.
- **Open WebUI Notes changed since the 2026-10-16 ruling:** a note now holds pages with versions and a revision counter, a stale write is refused when the revision is sent, and quoted-text comments live in their own table. Still: no folders of notes, ProseMirror JSON beside the markdown, comments outside the markdown.
- **Open WebUI Knowledge:** nested directories now; text edits are last-write-wins.
- **Fits a sheaf:** private by default; a stable address across updates; every write a version, stale writes refused; a personal list with pins; nested per-user folders shared as a unit; an agent updates a page only by its address; comments to the agent, answered under its name.
- **Does not fit:** comments stored outside the file; a stored form that is not the markdown; content bound to a chat; sharing as a frozen copy; deletion after no visits; containers of one kind only; last write wins; publishing that needs the vendor's own sign-in.
