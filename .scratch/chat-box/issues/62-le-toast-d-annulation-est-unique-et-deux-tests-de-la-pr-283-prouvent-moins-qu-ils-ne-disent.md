# 62: Un seul élément de toast : le toast du deuxième fil remplace celui du premier ; et deux tests de la PR 283 prouvent moins qu'ils ne disent

**What to build:** Constats de la revue Opus 1 de la PR 283 (tickets 42 et 48), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-42-reviews/1.md` (GO, aucune classe a ou b), et de la revue de spec. Classe c (F1), d (F2, F3), à décider un par un : corriger, ou écrire la limite dans le SPEC.
- F1 (c) : `say()` n'a qu'un élément de toast. Avec le correctif du ticket 42, deux annulations de fils différents disent chacune leur toast, mais ~60 ms les séparent : la personne ne voit que le dernier, et l'avertissement « had already seen it » du premier fil est à l'écran moins de 60 ms si le second n'en a pas. Le ticket 42 disait aussi : un toast en attente peut remplacer celui d'une annulation de session (`cancel()`, « Tell … cancelled. If it had arrived, the session was told to stop. ») : non traité, inchangé.
- F2 (d) : `test_two_cancels_of_two_threads_in_a_row_say_one_toast_each` (tests/page/test_page_waiting_tell.py) met le même agent sur les deux fils et compte les changements du toast avec un `MutationObserver` : il sépare l'ancien toast fondu (« A and A ») de deux toasts, mais ne prouve pas que le toast d'un fil ne nomme que ses agents (case 2 du ticket 42, laissée décochée).
- F3 (d) : `test_a_second_cancel_while_the_first_is_out_keeps_what_the_first_saw` attend (`until(lambda: line(tab) == [] and len(held) >= 1)`) la réponse du premier `/_/cancel` seulement, pas celle du second, avant `release()` : une fenêtre étroite où le test passe sans le correctif (faux vert).

**Blocked by:** none

**Claimed by:** Isolde (PR 298)

**Status:** in-review (PR 298, branch chat-box/62)

**Par où commencer :** F3 d'abord (attendre les deux réponses, sur t-compute, jamais sur le portable ; vérifier le rouge sans le correctif), puis F2 (deux agents, un par fil : `Tokens().add` deux fois, un Tell chacun, le toast de chaque fil ne nomme que le sien). F1 : décider avec le propriétaire du SPEC entre limite écrite et correctif (file de toasts, ou un toast qui liste les fils).

- [x] F1 : décision écrite (corriger ou limite dans le SPEC), pour les deux moitiés
- [x] F2 : le test a deux agents et affirme le nom de chaque fil
- [x] F3 : le test attend les deux réponses et reste rouge sans le correctif

**Décision F1 (Rhea, 2026-11-14) : corriger.** `say()` met les toasts en file : chacun est montré à son tour, pour sa propre durée (2,6 s ; 7 s en rouge), jamais perdu ni coupé par le suivant, jamais empilés à l'écran. Les deux moitiés de F1 (deux fils ; le toast d'une annulation de session écrasé par une note de fil) en découlent. Fait dans la PR 298.

**Limites laissées (revue Opus 1, classe c, voir la poignée) :** la file n'a ni plafond ni fusion ; pas de pause visible entre deux toasts ; une rechargement de page perd la file.
