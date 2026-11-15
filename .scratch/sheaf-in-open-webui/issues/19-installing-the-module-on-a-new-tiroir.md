# 19: What a new tiroir ships of the module, and what someone must do by hand

**Type:** grilling
**Status:** resolved
**Blocked by:** none
**Map:** ../map.md

## Question

The destination makes sheaf a standard module of every tiroir. On a new tiroir (a client's, or tiroir-0 for Marina), what is there on day one without anyone's hand: the hub in proxy mode, the library door with `create`/`update`, the Catalog and "Actions" entries in Open WebUI's sidebar (ticket 06), each member's `loose-<short>` root, the tiroir's own GitHub App (ticket 14), the archive rule (ticket 13)? Which steps need a person, and whose: creating and installing the GitHub App, writing the default tiroir into each laptop's sheaf config (ticket 04), signing a laptop session in to the door (ticket 11)? Is the module on by default in the tiroir product, or turned on per tiroir, and how is it updated across the fleet?

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry, three rounds.

1. **Standard where Open WebUI runs.** tiroir Sheaf is part of building every tiroir that runs Open WebUI: a step of the build runbook (`tiroir/o/docs/docs/device-build-runbook.md`) right after Open WebUI and Caddy, made by the existing sheaf module stage (`tiroir/o/clients/modules/sheaf/`) in proxy mode, with the session verifier and the library door's `create`/`update`. A tiroir without Open WebUI gets none. No per-tiroir switch.
2. **Recorded in the registry.** Each box's entry in `clients/devices.yaml` gains `modules:`, naming the version (`sheaf: 1.0.3`). tiroir-tt, which has no entry today, needs one.
3. **Nothing by hand per member.** Every Open WebUI user becomes a member at first sign-in, with no config line; their `loose-<short>` root is made when the first rectoverso is sent to them; the sidebar entries (Sheaf, Actions) are there for everyone from day one; the 30-day archive rule (ticket 13) is the default. Consequence for the stage: the hand-listed `proxy.members` of `module.yaml` give way to members read from Open WebUI.
4. **The GitHub App is Thierry's hand, once per tiroir.** He creates it through GitHub's manifest flow from a link the install prints, under sweatshop-ai, client tiroirs included; installing it on an org with selected repos stays one click by that org's owner (ticket 14). The module runs without it: loose rectoversos work, repo rectoversos fall back to the laptop hub with the install link.
5. **A laptop is connected by its member.** "Connect a laptop" in the Sheaf names the laptop, makes its agent token (ticket 11) and shows one line, `sheaf connect <tiroir-url> <token>`, which stores the token in the keyring, adds the library door to Claude Code's MCP entries and writes this tiroir as the laptop's default (ticket 04) when it has none. Thierry runs it for a member who is not technical. Revoked by name from the Sheaf.
6. **Updates: one pinned version per box.** A sheafmd release (version + wheel SHA-256) goes to tiroir-tt first, then to the other boxes once it ran clean there; an agent runs the module's stage on each (backup and rollback written: production rule 1) and updates `devices.yaml`. No auto-update and no fleet tool in this spec. The laptop CLI accepts any door version it meets, not one exact version.
7. **Naming, decided here.** The product is **tiroir Sheaf**; one page is **a rectoverso** (the agent's recto, the member's verso); a member's tree of folders is **the Sheaf**, which replaces the Catalog. This overrides ticket 15's "tiroir Recto". SPEC.md and the code are renamed at the build.

## Working notes (grilling, Ottilie with Thierry, 2026-11-15)

Facts gathered first (Explore subagent, local files only): no script, image or cloud-init builds a tiroir; tiroir-0 was built by hand from `tiroir/o/docs/docs/device-build-runbook.md` (Open WebUI + Caddy is step 10). Every change on a box is a per-box stage (preflight, dry-run, apply, verify, rollback); no fleet deploy tool, no auto-update. The sheaf module exists as `tiroir/o/clients/modules/sheaf/` (`module.yaml` + stage, modes loopback/proxy, members listed by hand in params, versions pinned by sheafmd version + wheel SHA-256); nothing records which modules a box runs. The library door deploys per box with `library-mcp/scripts/deploy-library-mcp.sh`. Tiroirs in the registry: tiroir-0, tiroir-chienvert, tiroir-respace (+ tiroir-avetta-o pending); tiroir-tt has no registry entry. Open WebUI is known on tiroir-tt and tiroir-0 only.

Round 1, accepted as recommended:
- Q1: every Open WebUI user becomes a member at first sign-in, no config; their `loose-<short>` root is made at the first page sent to them; the sidebar entries are there for everyone from day one; the 30-day archive rule is the default.
- Q2: Thierry creates each tiroir's GitHub App through GitHub's manifest flow (a link the install prints), under sweatshop-ai, client tiroirs included; installing it on an org stays one click by that org's owner; the module works without it (loose pages yes, repo pages fall back, ticket 14).
- Q3: "Connect a laptop" in the Catalog makes a named agent token and shows one line, `sheaf connect <tiroir-url> <token>`, which stores the token in the keyring, adds the MCP entry to Claude Code and writes this tiroir as the laptop's default when it has none; done by the member, by Thierry for a member who is not technical; revoked by name from the Catalog.
- Naming, in passing: the product is **tiroir Rectoverso**, one word (a short "Recto" is lost in dictation); ticket 15, the map and `GLOSSARY.md` amended.

Round 2, accepted as recommended:
- Q4: Rectoverso is standard on every tiroir that runs Open WebUI: a step of the build runbook after Open WebUI and Caddy, the existing sheaf module stage in proxy mode; a tiroir without Open WebUI gets none. Each box's entry in `clients/devices.yaml` gains a `modules:` field naming the version (`sheaf: 1.0.3`).
- Q5: one pinned version per box (sheafmd version + wheel SHA-256); a release goes to tiroir-tt first, then to the others once it ran clean there; an agent runs the module's stage (backup and rollback written: production rule 1) and updates `devices.yaml`; no auto-update, no fleet tool in this spec; the laptop CLI accepts any door version it meets rather than one exact version.

Round 3, naming (Thierry's "shift" was dictation for "Sheaf"):
- Two models shown: A (ticket 15: Rectoverso the product, a page a page, Catalog spec-only) and B (one page is a rectoverso, a sheet with the agent's recto and the member's verso; all of a member's pages are their Sheaf). Thierry chose B against the recommendation.
- The product is **tiroir Sheaf**: one name for the product, the sidebar entry, the engine and the laptop command (`sheaf FILE.md` sends a rectoverso to your Sheaf).
- In this map's spec one page is **a rectoverso** and the member's tree is **the Sheaf** (was the Catalog); SPEC.md (9.10/9.11 still say "a sheaf" for one page), the code and the older glossary entries are renamed at the build, not now. `GLOSSARY.md` updated (Sheaf, Rectoverso; Catalog and Recto now avoided).
