# Apps run sealed on a domain of their own, never on the front's origin

Status: accepted (2026-11-24, Thierry, wayfinder `sheaf-modular-editor` ticket 05)

A rectoverso may hold an App: code that a member or an assistant wrote and that runs when the page shows it, as an Artifact does. The front serves sheaf on its own origin behind its sign-in (tiroir-tt ADR 0002), and a mounted page runs inside Open WebUI's document with no policy of its own, so a script there acts as the member. Every App therefore runs in a frame with `sandbox="allow-scripts"` and no same-origin access, loaded from one Apps host on a registrable domain that is not ours for anything else (working name `tiroirusercontent.com`, bought at build time). The frame's URL carries a pass the hub signs for one page view (rectoverso, block, version, about a minute); the Apps host has no sign-in, serves `noindex` and a disallow-all `robots.txt`, and answers with a sealed policy (no network, no outside loads, framed only by the front). A share copy carries its Apps inline as a sandboxed `srcdoc` frame with the same policy in a `<meta>` tag; the laptop hub uses a second loopback port; a front with no Apps host shows an App as locked code.

## Considered options

- **A sandboxed `srcdoc` frame inside the page.** Rejected online: the frame inherits the parent's CSP, which inside the front is Open WebUI's and not sheaf's to set, and the hub's own CSP would have to allow inline script. Kept for the share copy, which has no parent policy and no hub.
- **A host under tiroir.me (`apps.tiroir.me`).** Rejected: a separate origin but the same site as the front, so if the sandbox ever fails the browser sends the front's same-site cookies with the escaped script's requests. A domain of its own costs about €10 a year.
- **One host per front (`thinkingtoo.…`, `avetta.…`).** Rejected: every certificate is published in certificate-transparency logs, so per-client hostnames publish the client list; the sandbox already gives every App an opaque origin, so one host costs no isolation.
- **Ruling runnable code out of the effort.** Rejected by Thierry: sheaf as a model-agnostic alternative to Artifacts includes code that runs.

## Consequences

- Buying the domain, adding it to Cloudflare and one DNS record are Thierry's hand; Caddy on the box gets a second site pointing to the same hub.
- The front's CSP (2026-11-24: `object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'`) has no `frame-src`, so Open WebUI needs no change. If it ever gains one, it must list the Apps host.
- An App in v1 is sealed: no network, no storage that survives a reload, no page text, no member identity. Each of those is a later capability with its own decision.
- No script written by an author or agent ever runs on the front's origin; interactive behaviour of any other Block type is sheaf's own nonce-signed script, never the page's.
- An App needs no separate write permission: whoever may edit the rectoverso may write one, through the editor or MCP.
