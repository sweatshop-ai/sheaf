# 01: What sheaf and Open WebUI run today on tiroir-tt and tiroir-0

**Type:** research
**Status:** open
**Blocked by:** none
**Map:** ../map.md

## Question

What is deployed today, as observed on the machines, not as remembered? On tiroir-tt: the sheaf hub (version, `config.toml`: proxy mode, roots, members, `[list]`), the Caddy routes and `forward_auth` in front of it, the verifier, and whether the Open WebUI sidebar entry (`/static/loader.js`) exists. On tiroir-0: whether Open WebUI runs, its users (Marina, Thierry), and whether any sheaf runs. On both: does Caddy serve the hub over HTTP/2 (which removes the six-connections limit of ticket 160)? Read-only: no change on either machine.
