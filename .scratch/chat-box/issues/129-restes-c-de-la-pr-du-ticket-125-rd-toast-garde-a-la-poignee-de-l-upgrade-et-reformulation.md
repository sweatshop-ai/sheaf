# 129: Restes c et d de la PR du ticket 125 (`rd-toast` après un rechargement qui n'a pas eu lieu)

**What to build:** Revues Opus de la branche `chat-box/125` (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-125-reviews/opus-round1.md` et `reread-after-verdict.md`).

- (c) Poignée de l'upgrade : `mount.js` ~400 appelle `page.failed(msg)` puis le chargeur monte la nouvelle version, dont `root.replaceChildren` (~440) retire le toast que `failed()` vient de dire (2,6 s) ; la ligne rouge qui le suit n'est jamais vue. Avant le ticket 125, la nouvelle page disait ce toast en entier. Piste : `failed(msg, handover)` qui laisse `rd-toast` pour le nouveau boot.
- (c) Aucun test ne couvre le cas que le SPEC dit garder : un rechargement tenu par un formulaire, puis abandonné. Aucun test non plus pour `failed()` qui dit le toast avant sa ligne.
- (d) SPEC 10.11 : « says it on the page that stays » est faux pour l'appelant de l'upgrade ; « (8.2) » omet 8.12 (fin d'accès), qui passe par `meetDocGone`.
- (d) `settle()` qui renonce après une fusion non sauvée est un troisième cas de rechargement qui n'a pas lieu ; le SPEC le dit à part, vérifier la formulation.

**Blocked by:** none (125 merged, bf55b05)

**Claimed by:** Freya 2026-11-15

**Status:** done (PR 368 merged as 95d46ea)

**Par où commencer :** `src/sheafmd/page/mount.js` ~400, `page.js` `failed()` ; tests dans `tests/page/test_mount_page.py` ; sur le serveur auto-hébergé, jamais sur le portable.

- [x] Le toast d'une fusion n'est pas perdu quand l'upgrade prend la main, ou le SPEC dit pourquoi
