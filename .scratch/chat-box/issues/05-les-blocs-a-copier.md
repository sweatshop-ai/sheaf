# 05: Les blocs à copier

**What to build:** Quand un agent prépare un mail, un titre, une instruction ou un prompt, il l'écrit dans un bloc citation marqué `> [!COPY]`. La page l'affiche comme une citation, toujours modifiable, avec un bouton Copier. Le marquage reste lisible dans n'importe quel éditeur Markdown. Le skill `render-doc` dit aux agents de s'en servir.

**Blocked by:** 04

**Claimed by:** Torsten 2026-11-11 00:01

**Status:** in-review (PR #240, tête 544ee32, CI verte ; reste la case du skill, à Isolde)

- [x] Le bouton Copier copie le texte du bloc tel qu'il est à l'écran, modifications comprises — `tests/page/test_page_copy_blocks.py::test_copy_puts_the_block_as_shown_on_the_clipboard` et `::test_copy_takes_the_text_typed_in_edit_mode_before_it_is_saved` (presse-papiers lu dans Chromium, texte non enregistré compris) ; `::test_the_text_copied_leaves_the_comment_badge_out`
- [x] Le bloc se modifie en mode Edit et se commente en mode Comment comme une citation — `::test_an_edit_is_saved_with_the_marker_and_without_the_button`, `::test_entering_edit_mode_does_not_make_the_block_changed`, `::test_a_comment_on_the_block_is_anchored_in_the_source_after_the_selected_words` ; côté serveur `tests/test_copy_blocks.py` (sauvegarde, fusion, décalages des commentaires lus dans l'arbre de pandoc)
- [x] La copie partagée sans script et le PDF montrent une citation normale, sans bouton — `tests/test_copy_blocks.py::test_the_share_copy_shows_a_plain_quote_without_marker_class_or_script` (ni marqueur, ni classe, ni bouton, ni script ; le PDF est imprimé depuis cette copie)
- [ ] Le skill `render-doc` et la spec décrivent le marquage — spec faite (SPEC 6.8, GLOSSARY « Copy block ») ; le paragraphe du skill est rédigé dans `~/.claude/pm/chat-box-handoffs/handoff-Torsten-2026-11-11.md`, non committé : à Isolde, une fois le rendu arrivé sur le hub (R22)
- [x] PR séparée, CI verte — PR #240, tête 544ee32, run 42923857640 refait puis run sur 544ee32 : 1 check (ubuntu-24.04 py3.13), success ; revues Opus en 4 passes, GO sur 7e373a0 (issuecomment-6783899357), 544ee32 ne change que `STAND_IN` et 2 tests, relu par Isolde
