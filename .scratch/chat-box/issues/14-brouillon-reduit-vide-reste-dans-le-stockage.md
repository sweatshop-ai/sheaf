# 14: Un brouillon réduit dont on vide le champ reste dans le stockage

**What to build:** Rouvrir un brouillon de nouveau message réduit, vider son champ, puis fermer (× ou Échap) doit supprimer ce brouillon : l'indicateur « not sent » disparaît et le texte effacé ne revient pas à la sélection suivante. Issu de la revue Codex de la fusion cdb0e24 (c562fc1..cdb0e24), trouvaille P2 n° 1.

**Blocked by:** 04

**Claimed by:** Isolde 2026-11-12 10:14

**Status:** in-progress

**Ce qui ne va pas :** `page.js:2783-2784`. Le `stash` du champ d'un nouveau message rend `true` dès que `box.value.trim()` est vide, sans passer par `draftsReplace(own)`. L'entrée `min: true` écrite à la première fermeture reste donc dans `localStorage`. Codex propose de vider `own` dans la branche vide avant de laisser fermer.

- [x] Brouillon réduit rouvert, champ vidé, × ou Échap : l'entrée disparaît du stockage et l'indicateur « not sent » aussi — test_a_minimized_message_whose_field_is_emptied_is_gone_from_the_store_when_the_box_closes (9152707, b1b3f24)
- [x] Test rouge avant le correctif (la sélection suivante ne ramène pas le texte effacé) — red: timed out waiting for 'the not-sent line gone' before the fix (9152707)
- [x] Un champ jamais enregistré et vide ne change rien ; un champ rempli se garde comme avant — test_closing_an_empty_new_message_that_was_never_kept_changes_nothing; the filled-field keep is test_minimize_closes_the_box_and_the_text_comes_back_even_after_a_reload
- [ ] PR séparée, CI verte
