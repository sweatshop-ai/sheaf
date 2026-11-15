# 106: Un CR avant la sélection : le commentaire tombe un caractère trop tôt par CR (restes de la PR 332)

**What to build:** Reste c de la relecture étroite de la PR 332 (tickets 103 et 95), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-103-reviews/opus-2-narrow.md`. Quand un CR précède la sélection dans le bloc, `comments.py` (`anchor_point` / projection, vers la ligne 594) place le commentaire un caractère trop tôt par CR : `para\r Title` donne `Titl<!--…-->e`, `\r> quote Title` pareil. Déjà vrai sur main. La PR 332 le rend atteignable dans plus de documents : quatre CR ou plus avant un bloc faisaient du code indenté (commentaire refusé), ce sont maintenant un paragraphe, une citation ou une liste, et le commentaire est ajouté, 4 caractères trop tôt. Entrée : `\r\r\r\r> quote Title\n`, commentaire sur « Title » → `\r\r\r\r> quote T<!-- sheaf-comment … -->itle`. La page est identique (le mot reste entier à l'écran) ; seul le texte brut est abîmé. À mesurer contre pandoc 3.9 avant le correctif ; test rouge d'abord.

**Autre reste (même relecture) :** `edit.TASK_MARK_RE` (l. 718, usages 754 et 782) ne reconnaît pas une liste devenue liste par ses 4 CR de tête (`\r\r\r\r- [ ] x`) : cocher la case passe par la sauvegarde pandoc normale au lieu de basculer une marque. Rien n'est perdu ; à écarter avec la preuve ou à aligner.

**Blocked by:** none

**Claimed by:** Halima

**Status:** done (PR 340, merge c5589ec; leftovers in ticket 113)

- [x] Le commentaire tombe après la sélection quand des CR la précèdent, mesuré contre pandoc 3.9 (PR 340, merge c5589ec : `anchor_point` travaille sur le bloc sans CR et reporte le point, `tests/test_anchoring.py::test_a_cr_before_the_selection_does_not_pull_the_comment_into_the_word`, rouge d'abord ; mesuré sur pandoc 3.7.0.2 en local, la CI épinglée a passé au merge)
- [x] `TASK_MARK_RE` : corrigé ou écarté avec la preuve (PR 340 : corrigé, la regex accepte les CR de tête, `edit.py:718`, `tests/test_hub_list.py::test_a_list_made_by_its_leading_crs_has_its_marks_found`)
