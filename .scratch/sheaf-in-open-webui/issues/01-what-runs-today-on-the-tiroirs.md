# 01: What sheaf and Open WebUI run today on tiroir-tt and tiroir-0

**Type:** research
**Status:** resolved
**Blocked by:** none
**Map:** ../map.md

## Question

What is deployed today, as observed on the machines, not as remembered? On tiroir-tt: the sheaf hub (version, `config.toml`: proxy mode, roots, members, `[list]`), the Caddy routes and `forward_auth` in front of it, the verifier, and whether the Open WebUI sidebar entry (`/static/loader.js`) exists. On tiroir-0: whether Open WebUI runs, its users (Marina, Thierry), and whether any sheaf runs. On both: does Caddy serve the hub over HTTP/2 (which removes the six-connections limit of ticket 160)? Read-only: no change on either machine.

## Answer

Resolved 2026-11-15 by a research subagent of Frida, read-only on both boxes. Full findings: `.scratch/sheaf-in-open-webui/research/01-what-runs-today.md` on branch `research/01-what-runs-today` (commit 1b3d971), **local only**: the auto-mode classifier refused the branch push twice, so it lives in the worktree `.claude/worktrees/agent-abfe352ebe336c2e9` until Thierry pushes it.

- **tiroir-tt:** one sheaf hub, sheafmd 1.0.3 pinned to `81c39b8` (PR #315, 2026-11-14), account `sheaf-mails`, proxy mode on `https://thinkingtoo.tiroir.me`. Four members = the four Open WebUI users (Thierry, Sven, Hans, Marina). Roots `list` (clone of `thinkingtoo/tiroir-sheaves`, 70 pages) and `private-thierry` (813 pages).
- **Front and sidebar on tiroir-tt:** Caddy 2.11.4, `forward_auth` to `tiroir-session-verify` (reads Open WebUI's `token` cookie, answers `X-Sheaf-Member`); `/_/mcp` only on a tailnet Caddy at 100.123.164.81:8773. `/static/loader.js` adds "Actions" (mounts `/list` via `/_/mount.js`, no iframe), "FleetView" and "Brain"; `/private-thierry` has a route but no sidebar entry. Open WebUI 0.11.4.
- **tiroir-0:** Open WebUI 0.11.4 at `o.tiroir.me`, users Thierry, Marina, test `u2`. No sheaf in proxy mode, no verifier, no loader. Only `sheaf-brain`, a read-only loopback hub over `/root/brain` (older `47fba4d`), plain HTTP on the tailnet at :8775: the "Brain" entry of tiroir-tt.
- **HTTP/2:** `thinkingtoo.tiroir.me` and `o.tiroir.me` answer HTTP/2 from Caddy, so ticket 160's six-connection limit does not apply to pages served there; it still applies to the laptop hub and to the brain hub (HTTP/1.1). A signed-in `/_/live` stream over HTTP/2 was not tested.
- **Meaning for the map:** on tiroir-tt the module half exists already (proxy mode, members, a private root per person, a sidebar mount); what is missing there is a Catalog entry. On tiroir-0 everything is missing.
