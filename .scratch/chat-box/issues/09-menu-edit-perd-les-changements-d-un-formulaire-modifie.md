# 09: Menu ⋯ Edit : les changements d'un formulaire d'édition déjà modifié sont perdus

**What to build:** Ouvrir ⋯ → Edit pendant qu'un formulaire d'édition contenant des changements est ouvert ne doit pas faire perdre ces changements. Issu de la review du bug hunt de la PR #238 (P2 n° 3) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Claimed by:** Birgit 2026-11-11 00:18

**Status:** done (PR à ouvrir)

**Ce qui ne va pas :** `page.js:2032`. Avec un formulaire d'édition ouvert et modifié, ⋯ → Edit perd les changements au Save ou Cancel suivant. Ce défaut existait avant la PR #238 : la PR ne l'a pas introduit, et la review l'a classé P2 pour cette raison.

- [x] Avec un formulaire d'édition modifié ouvert, ⋯ → Edit ne perd aucun changement au Save ni au Cancel suivant
- [x] Test qui reproduit le cas, rouge avant le correctif
- [x] Le cas sans changement (formulaire intact) se comporte comme avant
- [ ] PR séparée, CI verte

**Preuve (2026-11-11):** `test_choosing_edit_again_on_a_changed_edit_form_keeps_the_changes` (tests/page/test_page_chat_box.py), rouge avant (« assert 'Mine' == 'Mine, changed' »), vert après. `editForm` laisse en place un formulaire d'édition dont le texte diffère du message et lui rend le curseur ; le cas intact reste rouvert à neuf : `test_choosing_edit_again_on_an_unchanged_edit_form_opens_it_afresh`, vert avant et après. « PR séparée » : voir le ticket 08, une seule PR pour 08, 09, 11, 07 (consigne d'Isolde).

**Après la revue Opus (2026-11-11):** le garde de 09 mesure le formulaire contre le texte avec lequel il s'est ouvert (`f.began`), pas contre `c.body`, et ne regarde que le formulaire de ce fil (`ownForm()`) : `test_choosing_edit_on_an_edit_form_the_message_moved_away_from_opens_it_afresh`.
