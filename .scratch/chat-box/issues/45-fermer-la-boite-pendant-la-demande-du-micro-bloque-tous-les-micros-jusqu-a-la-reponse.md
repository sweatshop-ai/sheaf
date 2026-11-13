# 45: Fermer la boîte pendant l'invite d'autorisation du micro bloque tous les boutons micro jusqu'à la réponse de la personne

**What to build:** Dans `src/sheafmd/page/page.js` (branche `chat-box/06-page`, ticket 06 PR 2), le premier appui sur le micro appelle `getUserMedia` et pose `dict = {f, chunks, discard:false, rec:null}`. Tant que l'invite du navigateur reste ouverte, `stopDictation(true)` (Échap, fermeture de la boîte) ne fait que mettre `d.discard = true`, car `d.rec` et `d.abort` n'existent pas encore ; `dict` reste posé jusqu'à ce que la personne réponde à l'invite. Pendant ce temps, dans une boîte rouverte, `if (dict) { ...; return; }` (début du gestionnaire de clic) fait que chaque bouton micro ne fait rien, sans signe. Quand le flux arrive, il est bien relâché (`d.discard` → `release(); dict = null`). Le ticket demande de **décider** : (a) `stopDictation(true)` met `dict = null` tout de suite et le rappel de `getUserMedia` teste `dict !== d` en plus de `d.discard`, ou (b) un clic sur un autre formulaire remplace un `dict` encore sans `rec`. Classe : c, trouvé par la revue ronde 2 (Opus, repli de Codex) de la PR 2 du ticket 06 ; antérieur au correctif de la ronde 1, rejeté pour cette PR par Halima.

**Blocked by:** none

**Établi (preuves) :** lecture du code seulement (`page.js`, gestionnaire de clic de `dictation()` et `stopDictation`), aucun test ne l'exerce.

**Par où commencer :** un test de page dont `getUserMedia` reste en suspens (promesse tenue par le test), qui ferme la boîte avec Échap, la rouvre, appuie sur le micro et attend un deuxième `getUserMedia` (`window.__mic.asked === 2`) ; il échoue tant que `dict` bloque.

- [ ] La décision (a ou b) est écrite dans le ticket avant le code
- [ ] Un test de page échoue tant que le micro d'une boîte rouverte ne répond pas pendant que l'invite de la précédente est ouverte

**Status:** ready-for-agent
