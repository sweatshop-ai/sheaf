# 07: Page montée : un toucher dans la zone vide de la boîte met le curseur dans le champ

**What to build:** Sur la page montée (shadow DOM), un toucher dans la zone vide de la boîte ne met pas le curseur dans le champ, alors que la spec le prévoit en repli. Issu de la review du bug hunt de la PR #238 (P2 n° 1) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Claimed by:** Birgit 2026-11-11 00:19

**Status:** done

**Ce qui ne va pas :** `page.js:2652-2656`. L'écouteur `touchend` est posé sur `document` ; sur la page montée il voit l'hôte du shadow DOM comme cible, donc `box.contains(e.target)` est faux et le champ n'est jamais focalisé. `tests/page/test_mount_touch.py` ne couvre que `letGoOfPageWords`, pas ce repli.

- [x] Sur la page montée, un toucher dans la zone vide de la boîte met le curseur dans le champ (test dans `tests/page/test_mount_touch.py`, rouge avant le correctif)
- [x] Même comportement sur la page autonome, inchangé
- [x] Un toucher hors de la boîte ne focalise rien
- [x] PR séparée, CI verte (PR #241, tête 97a051c, run 43006211442 tentatives 1 et 2 réussies, fusion 7dae7b2)

**Preuve (2026-11-11):** `test_on_the_mounted_page_a_tap_in_the_empty_area_of_the_box_puts_the_cursor_in_the_field` (tests/page/test_mount_touch.py), rouge avant le correctif (le champ n'a pas le curseur), vert après ; `test_on_the_mounted_page_a_tap_outside_the_box_focuses_nothing` vert. Correctif : l'écouteur `touchend` est posé sur `PAGE_EV` (la racine sur la page montée, `document` sur la page autonome), donc la cible est l'élément du formulaire et non l'hôte. Page autonome inchangée : `PAGE_EV` y est `document`, et `test_page_mobile_collapse.py` + `test_mount_touch.py` passent (8 tests).
