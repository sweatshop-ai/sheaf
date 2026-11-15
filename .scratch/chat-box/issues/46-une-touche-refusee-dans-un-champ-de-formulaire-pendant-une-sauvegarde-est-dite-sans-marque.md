# 46: Une touche refusée pendant une sauvegarde dans un `textarea` ou un `input` de `main` est dite par le toast mais ne laisse aucune marque

**What to build:** La garde `beforeinput` de `src/sheafmd/page/page.js` (ticket 43, PR 259) pose `rd-saving` sur `e.target.closest('[contenteditable="true"]')`. Si la touche refusée tombe dans un `textarea` ou un `input` à l'intérieur de `main` (un formulaire de commentaire ou de réponse), `closest` rend null : le toast « Saving… » est dit, mais le champ ne porte ni trait pointillé ni curseur `not-allowed`, et rien ne reste à l'écran une fois le toast parti (2600 ms). La garde refusait déjà ces touches avant le ticket 43 ; elles sont toujours perdues, seul le toast le dit.

**Blocked by:** none

**Établi (preuves) :** revue de spec de la PR 259 (`pr-43-reviews/standards.md`, section Spec (a)). Non reproduit par un test.

**Par où commencer :** dire d'abord si la garde doit refuser ces champs (une réponse de commentaire n'est pas dans la page envoyée) ; si oui, marquer le champ lui-même (`e.target`) quand il n'y a pas de bloc éditable, avec la même classe et le même retrait, et écrire un test de page : une touche dans le champ d'un formulaire ouvert pendant une sauvegarde retenue.

- [x] ~~Un test de page tape dans un champ de formulaire pendant une sauvegarde sans réponse et échoue tant que le champ ne porte pas de marque~~ Sans objet : le formulaire est hors de `main`. Remplacé par `test_page_writing.py::test_no_text_field_is_in_main_so_the_save_guard_never_sees_a_key_typed_in_a_form` et `test_sanitize.py::test_a_type_that_is_a_checkbox_only_after_trimming_is_no_checkbox` (PR 287)
- [x] ~~La marque part avec la sauvegarde et ne devient pas une modification~~ Sans objet : aucune marque n'est posée sur un champ de formulaire (PR 287)

**Claimed by:** Isolde 2026-11-14 01:33

**Status:** done

**Done:** PR 287, merge 050b878. The ticket's premise was wrong: the comment, reply and edit forms are in the popover, outside `main`, so the `beforeinput` guard never sees a key typed in them. PR 287 closed the one hole that could put a text field in `main` (sanitizer: `type` must be exactly `checkbox`) and pinned the structure with a page test. The nested `contenteditable` case went to ticket 67.
