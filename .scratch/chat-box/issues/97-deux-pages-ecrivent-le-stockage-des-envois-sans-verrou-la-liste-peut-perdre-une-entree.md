# 97: Deux pages écrivent le stockage des envois gardés sans verrou : une entrée peut en écraser une autre pendant 32 s

**What to build:** Reste c de la revue Opus de la PR 323 (ticket 64), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-64-reviews/opus-round1.md`. Dans `src/sheafmd/page/page.js` (`commentDraftsSave`, l. 1621-1624), le stockage des réponses et éditions gardées est une seule clé localStorage que deux pages de la même page lisent, modifient et écrivent, sans verrou ni relecture. Scénario : la page A traite son 500 avec une vue du stockage qui n'a pas encore l'écriture d'échec de B ; elle écrit `[B(out), A]` par-dessus `[B]`, et la liste « not sent » ne montre que A pendant 32 s (HELD). Non prouvé : cela dépend de la vitesse à laquelle Chromium transmet une écriture localStorage d'un rendu à l'autre. Établir d'abord si la fenêtre existe (test qui envoie deux échecs en même temps depuis deux pages), puis relire la clé juste avant d'écrire, ou fusionner par `rid`.

**Blocked by:** PR 323 fusionnée

**Claimed by:** Rashid

**Status:** done (PR 341 merged as 1dfe55d, narrowed to the proof; the fix lives on in ticket 121)
