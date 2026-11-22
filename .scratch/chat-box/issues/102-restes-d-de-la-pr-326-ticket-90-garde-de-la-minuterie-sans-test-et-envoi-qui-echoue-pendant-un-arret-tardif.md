# 102: Restes d de la PR 326 (ticket 90) : garde de la minuterie sans test, et envoi qui échoue pendant l'arrêt tardif d'un ancien enregistreur

**What to build:** Revue Opus de la PR 326 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-90-reviews/review-1.md`). Rien de classe a, b ni c ne reste. À reprendre, tout est de classe d :
1. `page.js:2605` : la garde `dict === d` de la minuterie de 120 s ne peut pas se déclencher aujourd'hui (la minuterie est toujours effacée avant que `dict` quitte `d`). Inoffensive comme filet ; aucun test ne l'isole. Décider : la garder avec un test qui force le cas, ou la retirer.
2. Le cas de `back()` : un envoi qui échoue rend la forme avant l'événement `stop` de l'ancien enregistreur (le faux enregistreur sait maintenant retenir ses événements : `mic.lateStop`, `flush()`). Le test du `stop` tardif ne couvre que le cas où Escape détache l'ancienne forme.

**Blocked by:** PR 326 (merged, 20b24c7)
**Claimed by:** Nia
**Status:** done (merged d990a53, PR 344)

## Outcome (Nia, PR 344)

1. **Garde de la minuterie : retirée.** `dict` n'est assigné qu'à quatre endroits (déclaration, `stopDictation(true)`, le départ, `free()`) ; chacun efface la minuterie avant, ou court avant qu'elle existe. Sans la garde, les 32 tests de dictée passent (le serveur auto-hébergé). Aucun test ne peut la forcer.
2. **Cas de `back()` : un vrai bug.** L'événement `stop` tardif de l'ancien enregistreur remettait au repos le bouton de la nouvelle prise de la même forme. Test rouge sur le serveur auto-hébergé (`aria-pressed` `false`), corrigé dans `here()`. La revue (classe a) a trouvé que la condition devait aussi laisser passer `idle()` sous un enregistrement d'une autre forme (`dict.f !== f`) : corrigé, sans test propre (le cas demande une forme renvoyée dans le popover d'un autre fil).
