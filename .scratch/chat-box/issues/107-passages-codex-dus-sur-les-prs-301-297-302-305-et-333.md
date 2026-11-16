# 107: Passages Codex dus sur les PR 301, 297, 302, 305, 333 et 300 (repris du ticket 82)

**What to build:** Cinq PR fusionnées n'ont eu que des revues d'Opus (Codex sans jetons). Un essai le 2026-11-14 a donné « Codex is out of tokens until Nov 15th, 2026 1:00 AM ». Pas de repli sur Opus : un autre modèle est le but. Pour chaque PR, lancer `/codex-review` sur le diff de la fusion contre son premier parent (worktree propre, détaché sur la fusion, `--base <premier parent>`), enregistrer le rapport dans `/home/tiroir/.claude/pm/chat-box-handoffs/pr-82-codex/pr-<N>.md`, classer chaque trouvaille a/b/c/d. Un a ou b : correction avec test rouge d'abord (mattpocock-skills:tdd). Un c ou d : ticket de suite. Pas de retour en arrière.

| Point (du ticket 82) | PR | Ticket d'origine | Fusion | Premier parent | Périmètre / pièces |
|---|---|---|---|---|---|
| 1 | 301 | 59 | e5e71ab | 37c99b1 | `SPEC.md`, `src/sheafmd/page/page.js`, `tests/page/test_page_chat_box.py` ; revues Opus : `pr-59-reviews/round-1.md`, `round-2.md` |
| 7 | 297 | 73 | 8bcd20b | 4acd660 | `src/sheafmd/hub/transcribe.py` (`git diff 4acd660..8bcd20b`) ; tour 3 Opus de secours : `pr-61-reviews/codex-3-opus-fallback.md` ; exec avec une consigne qui exige la ligne VERDICT |
| 8 | 302 | 60 | 37c99b1 | c7ab758 | diff de la PR 302 (ticket 81) |
| 9 | 305 | 44 | 0f3a90a | 027198f | `src/sheafmd/page/page.js`, `SPEC.md`, `tests/page/test_mount_dictation.py` ; revues Opus de secours : `pr-44-reviews/opus-fallback.md`, `opus-fallback-2-narrow.md` |

| (Rhea) | 333 | 104 | 0349e1d | 13214f0 | `SPEC.md`, `src/sheafmd/sanitize.py`, `tests/test_sanitize.py` ; sanitiseur ; revue Opus (Codex sans jetons) |
| (Birgit, ticket 142) | 300 | 72 | 1521562 | 0e723e9 | `src/sheafmd/comments.py` (lecteur des spans de code `_CodeSpanFinder`, `_comment_spans`, `_CELL_PIPE_RE`), `SPEC.md`, `tests/test_anchoring.py`, `tests/test_share_copy.py` ; revues Opus : `pr-72-reviews/opus-1.md`, `opus-2.md` |

(Chemins `pr-*-reviews/` sous `/home/tiroir/.claude/pm/chat-box-handoffs/`.)

**Blocked by:**
- External: Codex usage limit until 2026-11-20 14:10 (retried 2026-11-15: exit 7 on the three PRs that need Codex, listed in the table; the earlier 01:00 date was wrong)

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] Cinq rapports Codex enregistrés
- [ ] Chaque trouvaille classée a/b/c/d ; a et b corrigées avec un test rouge, c et d en tickets

**Classification (Yuki, 2026-11-15, Alice's review-by-risk rule of 2026-11-13: Codex only for gate, security, deploy or data PRs, once):**

| PR | Codex? | Why |
|---|---|---|
| 333 | yes | Sanitizer (`sanitize.py`): security. |
| 297 | yes | Hub `transcribe.py`: the audio relay and its auth. |
| 302 | yes | Hub Tells: lock order between `waiting.py` and `live.py`, and the `tells.json` write path (data, deadlock risk). |
| 305 | no | `page.js` dictation-off flag in sessionStorage: UI state. The 403 is enforced by the hub, so the page's memory of it is a convenience. |
| 301 | no | `page.js` redraw of the unsent line moved to a `setTimeout`: display timing. Opus reviewed it twice, and 355 rewrites the store it touches. |
| 300 | yes | Gate: `_mask_code`, built on the code-span reader this PR rewrote, decides in `render.py` (`_unclosed_line` path, line 610 on main) which text is code and so not an opener, for the share-copy check that refuses to ship a reviewer's note. A wrong span read can pass what the check should refuse (Birgit, ticket 142). |
| 303 | no | Changes which message a refusal shows (`UnclosedComment(empty=...)`) and the cell-border regex for placing a comment; the refusal itself is unchanged, and the code-span reader of 300 is the part that feeds the gate. Opus reviewed it, `pr-76-reviews/opus-1.md`. |

Briefs and worktrees were ready (exec mode, brief asks for a final `VERDICT: GO` or `VERDICT: NO-GO` line). Nothing was saved: no report exists yet.
