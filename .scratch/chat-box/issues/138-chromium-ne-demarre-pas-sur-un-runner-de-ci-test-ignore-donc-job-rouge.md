# 138: Chromium ne démarre pas sur un runner de CI : un test est ignoré, donc le job est rouge

**What to build:** Une tranche de CI passe tous ses tests de page puis échoue parce qu'un test est ignoré (la CI refuse tout skip) : `chromium cannot start here: BrowserType.launch: Target page, context or browser has been closed`.

- Run 43707514947 (PR 362, tête 2270bae), tranche 3/3, job 132791692071 : 370 passed, 1 skipped, `tests/page/test_mount_selection.py:187`. La même tranche relancée seule est passée : rien n'a changé dans le code.
- C'est le seul cas de ce genre vu par moi ; je n'ai pas cherché d'autres runs. Les échecs du ticket 100 (ticket 137) ne sont pas de cette famille : ce sont des tests qui échouent, pas un lancement qui échoue.

**À faire :** trouver la cause dans les logs du runner (mémoire, ressources, processus Chromium restés d'un autre job sur t-compute, sandbox, `/dev/shm`) avant tout retry ou délai. Chercher d'abord dans l'historique des runs : combien de fois, sur quel runner `t-compute-N`, à quelle charge, et si un test précédent ou un job voisin tenait la machine. Le correctif nomme la cause ; un retry ne la remplace pas.

**Blocked by:** none

**Claimed by:** Isolde 2026-11-15 12:38

**Status:** in-progress

- [ ] Le nombre de cas et les runners sont établis à partir des runs passés
- [ ] La cause est établie dans les logs du runner, pas supposée
- [ ] Le correctif traite la cause (pas un retry ni un délai seul)
