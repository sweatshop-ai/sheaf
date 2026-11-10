# 02: La sélection ouvre la boîte, bascule Comment / Edit, Ctrl+C

**What to build:** Sur desktop, en mode Comment, sélectionner du texte ouvre directement la boîte, le curseur dans le champ, sans passer par le bouton Comment. Une bascule Comment / Edit toujours visible près du menu rond rend le mode évident ; en Edit, une sélection ne fait que sélectionner. Les numéros ouvrent le fil dans les deux modes et la touche E bascule aussi. Tant que le champ est vide, Ctrl+C copie le passage sélectionné.

Le code est déjà sur la branche `cleo/chat-box` ; ce ticket finit le travail en adaptant les anciens tests.

**Blocked by:** 01 (les deux partagent l'aide de test qui crée un commentaire)

**Claimed by:** Reem 2026-11-09 20:28

**Status:** done

- [x] Les anciens tests de sélection décrivent l'ouverture directe ; une sélection refusée garde son bouton grisé avec la raison
  - Preuve : `uv run pytest tests/page -m page -rfE --tb=line` sur t-compute (clone de chat-box/02, `git rev-parse HEAD` b3e974a) : 699 passed, 4 skipped (paramètres WebKit), 0 failed. Premier run à 7566042 : 10 failed, tous dans test_page_writing.py, repris dans b3e974a. Les cinq cas de bouton refusé (params + cellule) passent sans changement.
- [x] Après l'ouverture, la boîte ne se referme pas sur le clic qui suit la sélection
  - Preuve : test_the_click_that_ends_a_real_double_click_or_drag_does_not_close_the_box_it_opened (vraie souris) passe sur t-compute. Mutation : écouteur `mousedown`→`click` ET `setTimeout(offerComment, 0)`→`offerComment()` : échoue (`Page.wait_for_selector: Timeout 20000ms exceeded`), code restauré (`cmp`). Écouteur seul sur click/mouseup/dblclick : le test reste vert, la boîte s'ouvre dans un timer après le clic.
- [x] Le passage reste marqué dans le texte tant que la boîte est ouverte
  - Preuve : test_the_passage_stays_marked_in_the_text_while_the_box_is_open_and_the_mark_goes_with_it passe sur t-compute. Mutation : ligne `CSS.highlights.set('rd-widened', new Highlight(t.range))` de newComment supprimée : `assert [] == ['Second paragraph']` (test_page_selection.py:151), code restauré.
- [x] Ctrl+C essayé pour de vrai dans un navigateur, pas seulement simulé
  - Preuve : test_page_chat_box.py `test_a_real_ctrl_c_*` (4, vrai `ControlOrMeta+c` puis vrai Ctrl+V dans un champ sonde) et test_mount_page (champ vide ; bulle du fil monté) : verts sur t-compute (Chromium, Firefox). Mutations montrées en session précédente (setData('') ; écouteur sur document ; écouteur global). Exception : la copie de la bulle monte saute sous WebKit, dont la copie de base est vide sur cette machine.
- [x] La page montée dans tiroir garde la bascule et l'ouverture directe
  - Preuve : test_the_mounted_page_keeps_the_mode_switch_and_a_selection_only_opens_the_box_in_comment_mode (chromium, firefox ; webkit sur le portable) et les tests de glissé dans la racine : verts. Mutations montrées : garde `if (editing)` retirée ; `if (!t.error && !COARSE.matches)`→`if (false)`.
- [x] La spec décrit ce comportement
  - Preuve : SPEC 10.4 : deux puces ajoutées (ouverture directe + Ctrl+C ; bascule, Edit sélectionne seulement, sélection debout, page montée). `uv run pytest tests/test_spec_page_pins.py` : 11 passed à b3e974a.
