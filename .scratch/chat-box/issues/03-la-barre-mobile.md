# 03: La barre mobile, essayée sur l'iPhone

**What to build:** Sur téléphone, une sélection ouvre la boîte d'elle-même, comme sur un ordinateur ; une barre qui ressemble au champ du chat n'apparaît plus que pour une sélection refusée. Si l'iPhone ne lève pas le clavier après une sélection, un toucher dans la zone vide de la boîte met le curseur dans le champ. Thierry essaie ce prototype sur son vrai iPhone par un lien Tailscale temporaire vers la page d'essai.

**Blocked by:** 02

**Claimed by:** Kenji 2026-11-09 21:31

**Status:** in-progress

- [x] Vérifié si le hub accepte d'être joint par un lien Tailscale temporaire ; sinon, simulation mobile montrée à la place
  Le hub refuse ce Host par conception ; un relais local (27529 vers 27519) réécrit Host et Origin. Preuve : `https://tiroir-xps-15-7590.tail23d36e.ts.net:8446/_/health` répond 200, et Thierry a ouvert la page sur son iPhone.
- [x] Une sélection ouvre la boîte d'elle-même ; la barre ne reste que pour une sélection refusée
  Remplace « Toucher la barre ouvre la boîte… » : à l'essai Thierry a choisi qu'une sélection ouvre la boîte (la barre demandait un toucher de trop). Preuve : `tests/page/test_page_mobile_bar.py` (boîte ouverte, pas de barre) et `test_page_selection.py`. Le curseur dans le champ n'est prouvé qu'en émulation : sur son iPhone il a dû toucher le champ (verdict de Thierry, 2026-11-09 : « quand je select, la chat apparaît en haut (ok) mais le curseur n'est pas dedans (il faut le toucher avant) »), voir la case suivante.
- [x] Toucher un numéro met le curseur dans le champ et lève le clavier
  Preuve : sa capture d'écran de 22:37 (clavier levé après un numéro) et `test_touching_a_number_puts_the_cursor_in_the_field_too`.
- [x] Après une sélection, un toucher dans la zone vide de la boîte met le curseur dans le champ
  Ajouté après l'essai : l'iPhone n'a pas levé le clavier tout seul après une sélection (limite de la plateforme, rien n'est forcé). Preuve : `tests/page/test_page_mobile_refocus.py`, dix tests en émulation de téléphone ; le clavier lui-même reste à voir sur l'iPhone, dans la validation ci-dessous.
- [ ] Le lien temporaire est retiré après l'essai
  Après le dernier mot de Thierry : mapping 8446, relais, hub.
- [ ] Thierry a validé au doigt
  Après son dernier essai.

## Changé après l'essai du 2026-11-09

- La case « Le menu Copier du téléphone reste utilisable pendant que la barre est là » est retirée : remplacée par le choix de Thierry qu'une sélection ouvre la boîte ; il n'y a plus de barre à côté du menu Copier d'iOS, sauf pour une sélection refusée.
- Le bouton Edit / Save a un bord de la couleur de la boule d'état (gris, vert, rouge), lu dans une seule variable : demande de Thierry à l'essai (`tests/page/test_page_mode_border.py`).
