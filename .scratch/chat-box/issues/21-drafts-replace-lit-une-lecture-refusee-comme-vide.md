# 21: draftsReplace lit une lecture refusée comme vide

**What to build:** Quand le navigateur refuse de lire le stockage (`localStorage.getItem` lève), `draftsReplace` ne doit pas écrire à partir d'une liste vide : il doit le dire et laisser les brouillons d'autres passages et d'autres fils où ils sont. Issu de la revue Codex du ticket 14 (a88669d..b1b3f24), trouvailles P1 et P2 mises de côté parce qu'elles touchent chaque appelant, pas le seul ticket 14.

**Blocked by:** 04

**Status:** ready-for-agent

**Ce qui ne va pas :** `page.js:1416-1418` : `commentDraftsRaw` rend `[]` quand `getItem` ou `JSON.parse` lève. `draftsReplace` (`page.js:1439-1444`) filtre cette liste vide et `commentDraftsSave` (`page.js:1427-1436`) écrit le résultat : si la lecture échoue et que l'écriture ou `removeItem` réussit, toute la clé partagée est vidée, brouillons des autres passages compris, et `storeOk` reste `true`. Le test manque aussi : l'aide de `tests/page/test_page_chat_box.py` (~381) ne fait refuser que `setItem`, jamais `getItem`. Codex propose de distinguer « vide » de « illisible » dans `commentDraftsRaw` et de ne rien écrire (`storeOk = false`) quand la lecture est refusée.

- [ ] `getItem` refuse puis l'écriture passe : aucun brouillon existant n'est perdu et `storeOk` est faux, avec un test rouge avant le correctif (l'aide de test fait refuser `getItem`)
