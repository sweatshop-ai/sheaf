# 83: Restes c/d de la PR 303 (ticket 76) : message du refus pour `<!-->`, précédence sur la note, spans de la ligne

**What to build:** Revue Opus de la PR 303 (Codex sans jetons jusqu'à 15 h le 2026-11-14) : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-76-reviews/opus-1.md`. Rien de classe a ni b ne reste (le b, un cas de test qui ne pouvait pas échouer, est corrigé dans la PR). À reprendre :
1. (c) `src/sheafmd/render.py:61-63` : le message du refus pour `<!-->` dit que la copie « takes a comment to run to the next -->, which would drop text the page shows ». Faux sur ce chemin : si un `-->` suit, `_dropped_text_line` refuse avant avec son propre message ; quand ce message-ci s'affiche, il n'y a pas de `-->` après et rien n'est perdu. Le refus est une décision. Retirer la clause fausse.
2. (c) `SPEC.md:401` dit que la copie est refusée avec le message de l'ouvreur vide ; or `# A <!--> b <!-- note -->` et `# A <!--> b\n\nKEEP1 <!-- note -->` reçoivent le message « swallows ». Dire lequel des deux selon qu'un `-->` suit, et ajouter ces deux cas au test.
3. (c) `render.py:58` et `~1045` : `empty` passe avant `note`. Pour `<!--> <!-- sheaf-comment id=c1 ...\ncorps\n`, l'utilisateur reçoit le message de l'ouvreur vide là où main donnait celui de la note d'un relecteur. Refusé quand même, rien ne fuit. Choisir et le tester.
4. (d) `render.py:~1042` : `COMMENT_RE.finditer` est refait pour chaque candidat `<!--` de la ligne (quadratique par ligne) ; calculer les empans une fois.
5. **Passage Codex dû, venu du ticket 76 :** `/codex-review --base` sur le diff de la PR 300 (merge 1521562, tête 190bc94), que Codex n'a pas pu faire (plus de jetons jusqu'à 15 h le 2026-11-14) ; ses trouvailles deviennent des tickets ou des corrections. Le passage sur la PR 303 (fusionnée ff5aaf7) est dû aussi.

**Blocked by:** none


**Par où commencer :** `tests/test_share_copy.py`, `test_the_refusal_of_an_empty_comment_opener_does_not_say_it_is_never_closed`.

- [x] ~~Points 1 à 5 traités~~ (struck: 1, 2 et 4 faits, PR 325 merge 2374c25 : message sans la clause fausse `src/sheafmd/render.py:75-82`, SPEC 6.2, empans calculés une fois ; le point 3 est déplacé au ticket 99 puis 115, le point 5 (passage Codex des PR 300 et 303) au ticket 99 puis 107 : moved to tickets 99, 115 and 107)
- [x] CI verte — merge 2374c25 : check-runs total_count 3, `ubuntu-24.04 py3.13 slice 1/3`, `2/3`, `3/3` success

**Claimed by:** Mauro 2026-11-14 18:51

**Status:** done (PR 325, merge 2374c25; point 3 lives on in ticket 99)
