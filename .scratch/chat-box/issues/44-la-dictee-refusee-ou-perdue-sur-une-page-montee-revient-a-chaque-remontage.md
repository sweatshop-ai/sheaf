# 44: Sur une page montée, `dictOff` est perdu à chaque remontage : un micro refusé ou un service perdu fait échouer un appui de plus par remontage

**What to build:** Dans `src/sheafmd/page/page.js` (branche `chat-box/06-page`, ticket 06 PR 2), `dictOff` est déclaré avec `var dict = null, dictOff = 0;` dans la fermeture de la page. Sur une page montée dans Open WebUI (`MOUNTED`), il n'y a pas de sonde : le bouton est toujours offert (`dictationAvailable` rend `true`), et le premier échec met `dictOff = Infinity` (`why === 'denied'` : « Dictation is not allowed for your account. » ; `why === 'gone'` : « The transcription did not work. Try again. »), ce qui retire le bouton. Un remontage de la page (`opts.remount()`, par exemple après une réponse fusionnée ou un rechargement demandé par l'hôte) recrée la fermeture : `dictOff` revient à 0, le bouton revient, et la personne doit échouer une fois de plus (autre refus du micro, autre attente de transcription) pour le voir repartir. SPEC 10.4 dit « pour la session » ; le code le tient « pour ce montage ». Le ticket demande de **décider** où vit l'état : (a) hors de la fermeture, dans ce que l'hôte garde d'un montage à l'autre (par exemple `opts`), (b) le garder dans `sessionStorage` sous `KEYS` (le préfixe `sheaf-mount:`), ou (c) corriger le SPEC pour dire « jusqu'au prochain remontage » et ne rien changer. Classe : c, trouvé par la revue Codex ronde 1 de la PR 2 du ticket 06 (rejeté pour cette PR : ce n'est pas une régression de la PR, et la page non montée n'est pas touchée : elle redemande au hub à chaque ouverture de formulaire).

**Blocked by:**
- External: the PR of chat-box/06-page (ticket 06 page side) merged into main

**Établi (preuves) :**
- `page.js` sur `chat-box/06-page` : déclaration `var dict = null, dictOff = 0;` (ligne 2309), lecture dans `dictationAvailable` (ligne 2321), écriture `Infinity` sur `denied` et sur `gone` quand `MOUNTED` (lignes 2371 et 2372).
- Lecture du code (une lecture, pas une preuve) : aucun test ne remonte la page après un refus ; le comportement décrit vient de la portée de la variable, pas d'un run.

**Par où commencer :** un test de page monté qui refuse le micro, remonte la page (`opts.remount()` dans le banc de `tests/page/test_mount_dictation.py`) et vérifie si le bouton est revenu. Il échoue (bouton présent) tant que l'état est perdu, si la décision est (a) ou (b). Pour (c), pas de test : une ligne de SPEC 10.4.

- [ ] La décision (a, b ou c) est écrite dans le ticket avant le code
- [ ] Si (a) ou (b) : un test monté échoue tant que le bouton revient après un remontage qui suit un refus

**Claimed by:** —

**Status:** blocked (PR of chat-box/06-page)
