# 05: Les blocs à copier

**What to build:** Quand un agent prépare un mail, un titre, une instruction ou un prompt, il l'écrit dans un bloc citation marqué `> [!COPY]`. La page l'affiche comme une citation, toujours modifiable, avec un bouton Copier. Le marquage reste lisible dans n'importe quel éditeur Markdown. Le skill `render-doc` dit aux agents de s'en servir.

**Blocked by:** 04

**Claimed by:** Torsten 2026-11-11 00:01

**Status:** done (PR #240 fusionnée dans main 2883104, CI de main verte, run 43198417261 ; hub du portable sur 2883104)

- [x] Le bouton Copier copie le texte du bloc tel qu'il est à l'écran, modifications comprises — `tests/page/test_page_copy_blocks.py::test_copy_puts_the_block_as_shown_on_the_clipboard` et `::test_copy_takes_the_text_typed_in_edit_mode_before_it_is_saved` (presse-papiers lu dans Chromium, texte non enregistré compris) ; `::test_the_text_copied_leaves_the_comment_badge_out`
- [x] Le bloc se modifie en mode Edit et se commente en mode Comment comme une citation — `::test_an_edit_is_saved_with_the_marker_and_without_the_button`, `::test_entering_edit_mode_does_not_make_the_block_changed`, `::test_a_comment_on_the_block_is_anchored_in_the_source_after_the_selected_words` ; côté serveur `tests/test_copy_blocks.py` (sauvegarde, fusion, décalages des commentaires lus dans l'arbre de pandoc)
- [x] La copie partagée sans script et le PDF montrent une citation normale, sans bouton — `tests/test_copy_blocks.py::test_the_share_copy_shows_a_plain_quote_without_marker_class_or_script` (ni marqueur, ni classe, ni bouton, ni script ; le PDF est imprimé depuis cette copie)
- [x] Le skill `render-doc` et la spec décrivent le marquage — spec faite (SPEC 6.8, GLOSSARY « Copy block ») ; paragraphe « Blocks to copy » du skill committé dans thinkingtoo main 98e6205d9 (nothing deploys there). Preuve sur le hub du portable (sheafmd épinglé sur sheaf 2883104, pid 3049857, port 27419, démarré 2026-11-12 12:27:32+01) : un document de test avec `> [!COPY]` rendu par le hub sert `<blockquote class="rd-copy">` avec le bouton « Copy » (`aria-label="Copy this block"`), lu dans le Chrome connecté (curl reçoit 401) ; document de test supprimé
- [x] PR séparée, CI verte — PR #240, tête be5e909 (fusion de main 7dae7b2), run 43103502818 : total_count 1, `ubuntu-24.04 py3.13` success ; revues Opus en 4 passes, GO sur 7e373a0 (issuecomment-6783899357), 544ee32 relu par Isolde ; delta de la fusion : revue Codex de ce delta : aucun finding (commentaire de la PR, "Codex review 1 (run by Sami)")
