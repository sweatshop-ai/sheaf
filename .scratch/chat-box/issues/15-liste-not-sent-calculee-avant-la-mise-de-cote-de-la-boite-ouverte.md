# 15: La liste « not sent » est calculée avant que la boîte ouverte y mette son texte

**What to build:** Ouvrir la liste « not sent » pendant qu'une autre boîte contient un texte tapé doit afficher une liste qui correspond au compte. Issu de la revue Codex de la fusion cdb0e24 (c562fc1..cdb0e24), trouvaille P2 n° 2.

**Blocked by:** 04

**Claimed by:** Emil 2026-11-11 11:19

**Status:** in-progress

**Ce qui ne va pas :** `page.js:1634-1636` et `1534`. `showUnsent()` lit `ds = sendsKept()`, puis `keptForms` appelle `closePopover()`, qui met le texte de la boîte ouverte de côté comme nouveau brouillon. La liste est dessinée depuis `ds`, qui n'a pas ce brouillon : elle et le compte disent deux choses jusqu'à ce qu'on la ferme et la rouvre. Codex propose de fermer/mettre de côté avant de rassembler les entrées, ou de relire `ds` après.

- [x] Boîte ouverte avec un texte tapé, clic sur « not sent » : la liste montre ce texte, comme le compte — test_the_not_sent_list_opened_beside_an_open_box_holds_the_typed_text_as_the_count_does (a88669d)
- [x] Test rouge avant le correctif — red: 'the list does not match the count' before the fix (a88669d)
- [x] Sans boîte ouverte, comportement inchangé — test_the_not_sent_list_without_an_open_box_lists_what_was_kept (b1b3f24)
- [ ] PR séparée, CI verte
