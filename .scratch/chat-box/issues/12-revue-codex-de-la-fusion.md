# 12: Revue Codex de la fusion cdb0e24

**What to build:** Passer la chasse aux bugs de Codex sur la boîte de chat fusionnée. Codex n'a pas pu tourner pendant la PR #238 (plus de jetons jusqu'au 2026-11-11 08:36) ; un agent Opus l'a remplacé : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** Rien

**Claimed by:** Otilia 2026-11-11 11:11

**Status:** in-progress

- [x] `/codex-review` lancé le 2026-11-11 sur `c562fc1..cdb0e24` (35 fichiers, 2 962 lignes) ; Codex a répondu, pas de repli sur Opus. Verdict posté sur la PR #238
- [x] Chaque trouvaille devient un ticket numéroté à la suite (13, 14…) dans ce dossier et dans la table de `plan.md`, ou est écartée avec sa raison
- [x] Ce ticket nomme les tickets créés et le résultat de la revue, même si elle ne trouve rien

## Résultat de la revue (2026-11-11)

Codex : trois trouvailles P2, aucun P1. Les trois citations sont VERIFIED dans `cdb0e24`. Aucune n'est dans les tickets 07 à 11 ni 13, et ni la PR #240 (`chat-box/05`) ni la PR #241 (`chat-box/followups`) ne touchent `page.js`.

- [P2] `page.js:2783-2784`, brouillon réduit vidé jamais supprimé → ticket 14
- [P2] `page.js:1534` (avec `1634-1636`), liste « not sent » obsolète après la mise de côté → ticket 15
- [P2] `page.js:1800-1804`, × Close absent des fils en lecture seule → ticket 16

Aucune trouvaille écartée.
