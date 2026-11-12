# 17: Le test du toast d'annulation d'un Tell échoue de temps en temps en CI

**What to build:** Trouver la cause d'un échec CI intermittent qui n'est pas celui d'Échap (ticket 10, cause trouvée et corrigée). Test : `tests/page/test_page_writing.py::test_a_tell_or_cancel_the_hub_cannot_be_reached_for_says_that_it_did_not_go_out[cancel-tell]`.

**Blocked by:**
- 04

**Claimed by:** Elif 2026-11-12 10:01

**Status:** in-progress

L'attente du toast (8 s) expire. PR #241 run 42925663097 tentative 1 ; PR #240 run 42923857640 tentative 1 ; t-compute à 9aed290 (ticket 03). Pas la même cause qu'Échap (ticket 10) : le test n'appelle pas `fail_a_reply` et n'abandonne aucun envoi ; il ne se reproduit pas en local (12 passages). Le test relève maintenant le nombre de requêtes `/_/cancel` refusées, les toasts vus et le texte de la boîte (047a057) : le prochain rouge dit si le clic est perdu (0 requête) ou si le toast est remplacé (≥ 1).

- [ ] La cause est écrite avec la preuve (un échec reproduit à la demande, ou la sortie d'une CI qui l'a relevée)
- [ ] Le correctif traite la cause, pas un délai ou une relance
- [ ] CI verte sur trois passages de suite
