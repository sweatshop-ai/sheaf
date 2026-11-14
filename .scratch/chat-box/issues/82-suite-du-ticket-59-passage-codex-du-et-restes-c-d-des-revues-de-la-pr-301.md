# 82: Suite du ticket 59 (PR 301) : le passage Codex dû, et les restes c/d des revues

**What to build:** La PR 301 (ticket 59, fusionnée e5e71ab) a eu deux revues d'Opus (Codex sans jetons jusqu'à 15 h le 2026-11-14) : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-59-reviews/round-1.md` et `round-2.md`. Rien de classe a ou b ne reste. À reprendre :
1. **(→ ticket 107)** **Passage Codex dû :** `/codex-review --base` sur le diff de la PR 301 ; ses trouvailles deviennent des tickets ou des corrections.
2. (c) La liste « not sent » ouverte peut être fermée puis reconstruite pour rien : `showUnsent` ferme la fenêtre, sa propre lecture `sendsKept()` purge et met le redessin en file, `keptForms` ouvre la liste, le minuteur trouve `listed` et rappelle `showUnsent`. Sans perte de donnée ; perte du focus et du défilement dans la liste, sur la première lecture qui marche après un effacement gardé.
3. (d) SPEC, phrase d'ouverture et 4e puce du paragraphe ajouté : « la première lecture qui marche » et « chaque lecture réessaie l'écriture » ne tiennent pas pour les lectures du redessin différé, qui tournent sous la garde `flushing` et n'écrivent pas. Fenêtre de 0 ms ; un rechargement dedans ramène l'entrée une fois. Corriger la formulation du SPEC.
4. (d) Le test `test_a_redraw_of_the_not_sent_line_that_fails_after_a_purge_does_not_make_a_read_fail` n'a pas de témoin positif : il reste vert si la purge de l'effacement gardé disparaît (la liste de l'écrivain exclut déjà l'entrée effacée). Ajouter : l'entrée a quitté le stockage avant l'écriture tapée.
5. (d) Le test du stockage plein (`test_a_held_clear_that_the_full_store_cannot_write_...`) peut échouer sur un exécuteur lent si une lecture qui marche tombe entre `store_unreadable(p, False)` et `store_full(p)` (quelques ms) : fusionner les deux dans un seul `evaluate`. Il ne peut pas passer pour rien.
6. (d) `held_while_refusing` compte toute lecture refusée, pas seulement celle de l'effacement ; la preuve réelle est l'entrée encore dans le stockage. Dire plus fort ou resserrer.

7. **(→ ticket 107)** **Passage Codex dû sur la PR 297 (ticket 73, fusionnée 8bcd20b) :** le tour 3 a été fait par Opus de secours (Codex sans jetons jusqu'à 20 h le 2026-11-14), GO sur ad71cf2 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-61-reviews/codex-3-opus-fallback.md`). `/codex-review` (exec, avec une consigne qui exige la ligne VERDICT) sur `git diff 4acd660..8bcd20b -- src/sheafmd/hub/transcribe.py` ; ses trouvailles deviennent des tickets, pas un retour en arrière.

8. **(→ ticket 107)** **Passage Codex dû sur la PR 302 (ticket 60, fusionnée 37c99b1), venu du ticket 81 :** les deux revues sont d'Opus (Codex sans jetons jusqu'à 20 h le 2026-11-14). `/codex-review --base` sur le diff de la PR 302 ; ses trouvailles deviennent des tickets, pas un retour en arrière.

9. **(→ ticket 107)** **Passage Codex dû sur la PR 305 (ticket 44, fusionnée 0f3a90a) :** les deux revues sont d'Opus de secours (Codex sans jetons jusqu'à 20 h le 2026-11-14), GO : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-44-reviews/opus-fallback.md` et `opus-fallback-2-narrow.md`. `/codex-review --base` sur le diff de la PR 305 (`src/sheafmd/page/page.js`, `SPEC.md`, `tests/page/test_mount_dictation.py`) ; ses trouvailles deviennent des tickets, pas un retour en arrière.

**Blocked by:** none (les points 1, 7, 8 et 9 sont passés au ticket 107, Codex sans jetons jusqu'au 2026-11-15 01:00 ; ici : les points 2 à 6)

**Claimed by:** Elske

**Status:** ready-for-agent

- [ ] Chaque point est soit corrigé avec un test rouge, soit écarté avec la raison
- [ ] Le passage Codex sur le diff de la PR 301 est fait, ses trouvailles classées
