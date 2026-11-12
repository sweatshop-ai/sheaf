# 29: une boîte de nouveau commentaire au champ vidé ne se ferme plus quand le stockage refuse la lecture

**What to build:** Avec un champ vide, `stash` rend vrai même si l'effacement du brouillon gardé échoue, pour que la boîte se ferme.

**Blocked by:**
- External: PR 250 (ticket 21) merged into main

**Claimed by:** Isolde 2026-11-12 13:50

**Status:** in-progress — fixed in PR 250, waiting for merge

**Ce qui ne va pas :** `page.js` ~2881-2884 et 1269 : un brouillon gardé existe (`d`, `kept` ou `wrote`), la lecture devient refusée (depuis le ticket 21), l'utilisateur vide le champ et clique dehors : `draftsReplace(own)` n'écrit pas, `stash` rend faux, `closePopover` refuse, et le message « could not be kept » s'affiche au-dessus d'une boîte vide, à chaque clic dehors ou Échap jusqu'à ce que le stockage relise. Issu de la revue Opus du PR 250 (ticket 21), trouvaille P2 mise de côté (cas rare, aucune perte de texte tapé).

- [x] lecture refusée, champ vidé, clic dehors : la boîte se ferme, le brouillon gardé reste, test rouge avant le correctif
