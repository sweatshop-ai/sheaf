# 54: Le test d'un commentaire répondu pendant l'annulation attend un cochage qui n'arrive pas quand la machine est chargée

**What to build:** `test_a_comment_answered_during_the_undo_does_not_move_the_text_the_press_names` (`tests/page/test_page_actions.py`, ligne 550 sur main afbe595) échoue une fois sur seize sous charge : `AssertionError: timed out waiting for the tick` à la ligne 562, `until(lambda: "- [x] Approve" in f.read_text(...), what="the tick")`, après `p.wait_for_timeout(300)` et `p.clock.run_for(5100)`. Le test passe dans les quinze autres passages. Ce ticket cherche pourquoi le cochage n'arrive pas dans les 8 s, et corrige le test ou la page.

**Blocked by:** none

**Classe :** c (CI : un rouge sans lien avec le changement poussé, si la machine de CI est chargée comme t-compute l'était).

**Établi (preuves) :** sur t-compute (`~/work/sheaf-53`, branche chat-box/53 = main afbe595 + PR 268, hors CI), deux boucles de huit passages de `tests/page/test_page_actions.py` entier, quatre brûleurs de CPU en parallèle, `-n 2`, `--timeout=120` (script `loop53.sh`). Seconde boucle, passage 2 : `1 failed, 39 passed in 32.27s`, ce test seul rouge, `[gw1]`, trace dans `~/work/sheaf-53/keep/loop2-run2-tick-timeout.log` :
- `tests/page/test_page_actions.py:562` : `AssertionError: timed out waiting for the tick`, levée par `tests/page/pagehelp.py:184` (`until`, 8 s) ; ce n'est ni un figement du pilote ni une erreur de lecture du toast.
- Chaque étape précédente du test est passée : le commentaire « Why? » est dans le fichier (ligne 559), l'horloge de la page a avancé de 5100 ms (ligne 561).
- Non établi : si le cochage est sorti de la page (la requête `/_/tick` est partie mais le hub a répondu tard), ou si la page ne l'a pas envoyé (l'horloge installée par `sheaf` n'a pas livré le minuteur de l'annulation). Pas de passage de main sans la PR 268 sous la même charge ; la PR ne change que `toast()` et ses tests, ce test ne l'appelle pas.
- Un seul rouge sur seize : la fréquence est mal connue.

**Par où commencer :**
1. Reproduire sur t-compute (jamais ici : test de navigateur) : ce test seul, 50 à 100 passages sous quatre brûleurs (`-k test_a_comment_answered_during_the_undo`), avec `--timeout=120`, pour avoir une fréquence ; noter si le `POST /_/tick` est parti (`page.on("request")` ou le journal du hub).
2. Selon ce que montre la reproduction : si la requête n'est jamais partie, lire comment le minuteur de l'annulation de la page se pose sous `p.clock` quand un commentaire est répondu pendant l'annulation ; si elle est partie et a été lente, le délai de 8 s de `until` ne convient pas à cette attente et le test doit attendre l'événement (la requête), pas une durée.
3. Corriger la cause, pas le délai.

- [ ] La cause du rouge est écrite avec la preuve (une reproduction sur t-compute ou le traceback d'une apparition)
- [ ] Le correctif est dans le test ou dans la page, et un test pose le cas à la main
- [ ] Cent passages de ce test sous quatre brûleurs sur t-compute, aucun rouge de ce type

**Claimed by:** Elias 2026-11-13 02:05

**Status:** in-progress
