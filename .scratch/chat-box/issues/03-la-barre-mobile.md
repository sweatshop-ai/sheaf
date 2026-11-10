# 03: La barre mobile, essayée sur l'iPhone

**What to build:** Sur téléphone, une sélection ouvre la boîte d'elle-même, comme sur un ordinateur : le relâchement du doigt l'ouvre, curseur dans le champ, dans le même événement. Appui long = un mot, appui long + glisser = une phrase ; pas de poignées à déplacer après le relâchement. Une barre qui ressemble au champ du chat n'apparaît plus que pour une sélection refusée. Thierry essaie ce prototype sur son vrai iPhone par un lien Tailscale temporaire vers la page d'essai.

**Blocked by:** 02

**Claimed by:** Kenji 2026-11-09 21:31

**Status:** done

- [x] Vérifié si le hub accepte d'être joint par un lien Tailscale temporaire ; sinon, simulation mobile montrée à la place
  Le hub refuse ce Host par conception ; un relais local (27529 vers 27519) réécrit Host et Origin. Preuve : `https://tiroir-xps-15-7590.tail23d36e.ts.net:8446/_/health` répond 200, et Thierry a ouvert la page sur son iPhone.
- [x] Une sélection ouvre la boîte d'elle-même, le curseur dans le champ, au relâchement du doigt ; la barre ne reste que pour une sélection refusée
  Remplace « Toucher la barre ouvre la boîte… » (la barre demandait un toucher de trop) et la version du 2026-11-09 où le curseur demandait un toucher : l'iPhone resélectionne les mots de la page 1 à 7 ms après le focus, la page les lâche pendant 1 s. Preuve : `tests/page/test_page_mobile_collapse.py`, `test_page_mobile_bar.py`, `test_page_selection.py`. Sur l'iPhone : « ça marche à chaque coup » (essai 2, 2026-11-10).
- [x] Appui long = un mot, appui long + glisser = une phrase ; pas de poignées après le relâchement
  Ajouté : choix de Thierry (q14, 2026-11-10), « Ça me va : appui long = un mot, appui long + glisser = une phrase ». Les poignées sont impossibles parce que la page lâche la resélection d'iOS (« il n'est pas possible de déplacer les poignées (jamais) »). SPEC 8 et plan.md l'énoncent, sans menu Copier natif sur téléphone.
- [x] Un doigt posé n'ouvre rien : le délai de 600 ms attend le relâchement
  Ajouté après l'essai 2 : le délai ouvrait la boîte sous un doigt encore posé (touchDownAt, plafond 10 s). Preuve : deux tests dans `test_page_mobile_collapse.py`, mutation rouge. Prouvé en émulation seulement, pas sur l'iPhone.
- [x] Toucher un numéro met le curseur dans le champ et lève le clavier
  Preuve : sa capture d'écran de 22:37 (clavier levé après un numéro) et `test_touching_a_number_puts_the_cursor_in_the_field_too`.
- [x] Après une sélection, un toucher dans la zone vide de la boîte met le curseur dans le champ
  Ajouté après l'essai 1, gardé en repli après l'essai 2 (le curseur arrive seul au relâchement) : l'iPhone n'avait pas levé le clavier tout seul après une sélection. Preuve : `tests/page/test_page_mobile_refocus.py`, dix tests en émulation de téléphone ; le clavier lui-même reste à voir sur l'iPhone, dans la validation ci-dessous.
- [x] Le lien temporaire est retiré après l'essai
  2026-11-10, vérifié par Isolde après la commande de Thierry et revu par Kenji : le hub (2109646) et le relais (3548303) n'existent plus, rien n'écoute sur 27519 ni 27529, 27419 écoute toujours ; `tailscale serve status` montre 8443, 8444, 8445 et plus 8446. QR et fichiers de diagnostic effacés des scratchpads.
- [x] Thierry a validé au doigt
  Ses deux réponses du 2026-11-10 : essai 2 « ça marche à chaque coup mais attention, il n'est pas possible de déplacer les poignées (jamais) » ; choix q14 « Ça me va : appui long = un mot, appui long + glisser = une phrase ». Pas d'essai suivant.

## Changé après l'essai du 2026-11-09

- La case « Le menu Copier du téléphone reste utilisable pendant que la barre est là » est retirée : remplacée par le choix de Thierry qu'une sélection ouvre la boîte ; il n'y a plus de barre à côté du menu Copier d'iOS, sauf pour une sélection refusée.
- Le bouton Edit / Save a un bord de la couleur de la boule d'état (gris, vert, rouge), lu dans une seule variable : demande de Thierry à l'essai (`tests/page/test_page_mode_border.py`).
