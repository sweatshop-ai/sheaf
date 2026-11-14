# 107: Passages Codex dus sur les PR 301, 297, 302, 305 et 333 (repris du ticket 82)

**What to build:** Cinq PR fusionnées n'ont eu que des revues d'Opus (Codex sans jetons). Un essai le 2026-11-14 a donné « Codex is out of tokens until Nov 15th, 2026 1:00 AM ». Pas de repli sur Opus : un autre modèle est le but. Pour chaque PR, lancer `/codex-review` sur le diff de la fusion contre son premier parent (worktree propre, détaché sur la fusion, `--base <premier parent>`), enregistrer le rapport dans `/home/tiroir/.claude/pm/chat-box-handoffs/pr-82-codex/pr-<N>.md`, classer chaque trouvaille a/b/c/d. Un a ou b : correction avec test rouge d'abord (mattpocock-skills:tdd). Un c ou d : ticket de suite. Pas de retour en arrière.

| Point (du ticket 82) | PR | Ticket d'origine | Fusion | Premier parent | Périmètre / pièces |
|---|---|---|---|---|---|
| 1 | 301 | 59 | e5e71ab | 37c99b1 | `SPEC.md`, `src/sheafmd/page/page.js`, `tests/page/test_page_chat_box.py` ; revues Opus : `pr-59-reviews/round-1.md`, `round-2.md` |
| 7 | 297 | 73 | 8bcd20b | 4acd660 | `src/sheafmd/hub/transcribe.py` (`git diff 4acd660..8bcd20b`) ; tour 3 Opus de secours : `pr-61-reviews/codex-3-opus-fallback.md` ; exec avec une consigne qui exige la ligne VERDICT |
| 8 | 302 | 60 | 37c99b1 | c7ab758 | diff de la PR 302 (ticket 81) |
| 9 | 305 | 44 | 0f3a90a | 027198f | `src/sheafmd/page/page.js`, `SPEC.md`, `tests/page/test_mount_dictation.py` ; revues Opus de secours : `pr-44-reviews/opus-fallback.md`, `opus-fallback-2-narrow.md` |

| (Rhea) | 333 | 104 | 0349e1d | 13214f0 | `SPEC.md`, `src/sheafmd/sanitize.py`, `tests/test_sanitize.py` ; sanitiseur ; revue Opus (Codex sans jetons) |

(Chemins `pr-*-reviews/` sous `/home/tiroir/.claude/pm/chat-box-handoffs/`.)

**Blocked by:** Codex usage limit until 2026-11-15 01:00

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] Cinq rapports Codex enregistrés
- [ ] Chaque trouvaille classée a/b/c/d ; a et b corrigées avec un test rouge, c et d en tickets
