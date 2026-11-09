# 01: Le fil en boîte de chat : champ ouvert, bandeau, texte gardé

**What to build:** Ouvrir un fil montre une boîte de chat étroite, avec le curseur déjà dans le champ, sur desktop comme sur téléphone. Le bandeau du haut porte le passage cité, Minimize et Fermer. Minimize, Échap et un clic à côté ferment la boîte et gardent le texte ; il revient en cliquant sur le numéro, même après un rechargement. Fermer résout le fil, et un texte non envoyé part dans la liste « not sent ». Entrée envoie à l'agent, Maj+Entrée va à la ligne, et sans agent connecté le message reste un commentaire avec une ligne qui l'explique.

Le code est déjà sur la branche `cleo/chat-box` ; ce ticket finit le travail en adaptant les anciens tests au nouveau contrat.

**Blocked by:** None (can start immediately)

**Claimed by:** Suraya 2026-11-09 16:18

**Status:** done

- [x] Les anciens tests du formulaire décrivent le nouveau contrat : un champ vide n'est pas « en train d'écrire », un texte tapé est gardé au lieu de bloquer la fermeture, il n'y a plus de Cancel sauf pour Edit
  - Preuve : tests/page complet sur t-compute (clone de 4f826a6 puis 49b95c7, `-rfE --tb=line`) : 101 échecs au premier passage, 69 au second ; les 68 restants attendent `#rd-comment-btn` après une sélection (liste du ticket 02, par nom dans handoff-Suraya-2026-11-09c.md), et le 69e est corrigé en 99240fd (1 passed sur t-compute). Épingles hors page : `pytest tests/test_page_assets.py tests/test_spec_page_pins.py` 19 + 3 passed.
- [x] Un rechargement nécessaire n'est retenu que par un texte tapé, jamais par le champ vide
  - Preuve : `pytest tests/page/test_page_chat_box.py -k empty_box_does_not_hold` passe ; cassé exprès dans `writingNow` : `return false` fait échouer le test (« Timeout waiting .rd-hold »), `return !!(pop && pop.querySelector('textarea'))` le fait échouer (« timed out waiting for the page to reload »). Code rétabli.
- [x] La liste « not sent » nomme correctement un message sans numéro (aujourd'hui « 1 reply »)
  - Preuve : test_a_minimized_new_message_is_named_a_message_in_the_not_sent_line (rouge puis vert, session du matin) ; `pytest tests/page/test_page_chat_box.py tests/test_spec_page_pins.py` : 42 passed. Un ancien brouillon (sans `min`) reste « 1 reply not sent » : cassé exprès `kindOf` → « 1 message not sent » ≠ « 1 reply not sent », test en échec. Code rétabli.
- [x] Sur un fil résolu, × ferme simplement et Reopen est dans le menu ⋯ ; Edit et Delete y sont pour ses propres messages
  - Preuve : test_a_resolved_thread_closes_with_the_cross_and_reopens_from_the_menu et test_a_resolved_thread_of_another_person_has_no_edit_or_delete passent ; cassés exprès dans `bandHtml` (× devient Resolve : « assert 'Resolve' == 'Close' » ; `more = mine(c)` : clic sur ⋯ en timeout). Code rétabli.
- [x] Le fil s'ouvre sur son dernier message et défile vers le haut
  - Preuve : test_a_long_thread_opens_on_its_last_message_and_scrolls_up passe ; sans `sc.scrollTop = sc.scrollHeight` à l'ouverture il échoue : « AssertionError: (4995, 372, 5495) ». Code rétabli.
- [x] La spec décrit ce comportement
  - Preuve : SPEC.md §10.4 « The thread is a chat box » (ligne 1180) et §10.2 ; les épingles de spec (tests/test_spec_page_pins.py) passent, 42 passed avec le fichier chat_box. Relecture par une autre personne : pas faite.
