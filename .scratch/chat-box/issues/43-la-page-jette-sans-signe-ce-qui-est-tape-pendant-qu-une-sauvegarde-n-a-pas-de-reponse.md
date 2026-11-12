# 43: La page jette sans signe ce qui est tapé pendant qu'une sauvegarde n'a pas de réponse (`beforeinput` annulé quand `saving || settling`)

**What to build:** Dans `src/sheafmd/page/page.js` (ligne 3072 à la tête de `main`, 1172302), `main.addEventListener('beforeinput', function (e) { if (saving || settling) e.preventDefault(); })` annule toute frappe dans un bloc éditable tant qu'une sauvegarde est sortie ou qu'un `settle` tourne. La frappe ne va ni dans le DOM ni dans une file, et la page ne dit rien : une personne qui tape pendant que le hub tarde à répondre perd ses caractères sans le voir. Le commentaire de la ligne dit pourquoi (la page doit rester ce qui a été envoyé, car une réponse fusionnée recharge la page) et suppose qu'une sauvegarde « prend une fraction de seconde ». Le ticket demande de **décider** entre deux voies, pas de corriger ici : (a) mettre la frappe en file et la rejouer à la réponse, (b) montrer que la page est bloquée (curseur, bandeau « Saving… » sur le bloc, ou refus dit une fois). Classe : c, trouvé en cherchant l'échec de `test_what_is_saved_while_the_reload_waits_for_a_reply_is_merged_onto_the_change_from_outside[True-a save that merges]` sur la branche `chat-box/06-page` (ticket 06, PR 2).

**Blocked by:** aucun

**Établi (preuves) :**
- Le journal d'événements ajouté au test (branche jetable `chat-box/06-page-diag8b`, run 43281466845, py3.13) montre, pour " and kiwis" tapé dans le paragraphe 4 (`contenteditable`) : des `keydown` sur le `P`, aucun `input`, aucune mutation du DOM, le texte du paragraphe inchangé (« Last paragraph. »). Même dump dans les runs 43279028808 et 43279048753.
- Au moment de taper, le test comptait une sauvegarde sortie et sans réponse (`out=1`, run 43283685565), dont la route du test avait déjà laissé passer la requête. Après l'attente de cette réponse, 4 runs sur 4 verts (43285717862, 43285723130, 43285730988, 43285738359). Le test attend donc maintenant que plus aucune sauvegarde ne soit sortie avant de taper (commit `6b358fa` sur `chat-box/06-page`).
- Ctrl+S après cette frappe perdue dit « Nothing changed » : `dirty()` est vide.

**Lecture du code (une lecture, pas une preuve) :** le `GET /_/transcribe` que le bouton de dictée de la PR 2 (ticket 06) envoie à chaque ouverture de formulaire peut décaler ou allonger la fenêtre où la sauvegarde est sortie ; c'est ce qui rendrait l'échec du test probable avec le bouton et rare sans. Non prouvé : aucun run n'a mesuré la durée de la fenêtre avec et sans le bouton.

**Par où commencer :** mesurer la fenêtre (le temps entre l'envoi de `POST /_/save` et sa réponse, sur le hub réel et sur un hub lent), puis décider. Pour (a), `beforeinput` pourrait garder l'`inputType` et les données, puis les rejouer après `refresh()` ; attention à une réponse fusionnée qui recharge la page (les frappes en file doivent aller dans le bloc rechargé, ou être refusées). Pour (b), dire le blocage une fois par sauvegarde.

- [ ] Un test de page tape un caractère pendant qu'une sauvegarde n'a pas de réponse et échoue tant que la frappe est perdue sans signe
- [ ] La décision (file ou signe) est écrite dans le ticket avant le code

**Claimed by:** Saskia 2026-11-12

**Status:** in-progress
