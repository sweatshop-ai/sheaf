# 09: Menu ⋯ Edit : les changements d'un formulaire d'édition déjà modifié sont perdus

**What to build:** Ouvrir ⋯ → Edit pendant qu'un formulaire d'édition contenant des changements est ouvert ne doit pas faire perdre ces changements. Issu de la review du bug hunt de la PR #238 (P2 n° 3) : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6772147551

**Blocked by:** 04

**Claimed by:** Birgit 2026-11-11 00:18

**Status:** in-progress

**Ce qui ne va pas :** `page.js:2032`. Avec un formulaire d'édition ouvert et modifié, ⋯ → Edit perd les changements au Save ou Cancel suivant. Ce défaut existait avant la PR #238 : la PR ne l'a pas introduit, et la review l'a classé P2 pour cette raison.

- [ ] Avec un formulaire d'édition modifié ouvert, ⋯ → Edit ne perd aucun changement au Save ni au Cancel suivant
- [ ] Test qui reproduit le cas, rouge avant le correctif
- [ ] Le cas sans changement (formulaire intact) se comporte comme avant
- [ ] PR séparée, CI verte
