# 138: Chromium ne démarre pas sur un runner de CI : un test est ignoré, donc le job est rouge

**What to build:** Une tranche de CI passe tous ses tests de page puis échoue parce qu'un test est ignoré (la CI refuse tout skip) : `chromium cannot start here: BrowserType.launch: Target page, context or browser has been closed`.

- Run 43707514947 (PR 362, tête 2270bae), tranche 3/3, job 132791692071 : 370 passed, 1 skipped, `tests/page/test_mount_selection.py:187`. La même tranche relancée seule est passée : rien n'a changé dans le code.
- C'est le seul cas de ce genre vu par moi ; je n'ai pas cherché d'autres runs. Les échecs du ticket 100 (ticket 137) ne sont pas de cette famille : ce sont des tests qui échouent, pas un lancement qui échoue.

**À faire :** trouver la cause dans les logs du runner (mémoire, ressources, processus Chromium restés d'un autre job sur le serveur auto-hébergé, sandbox, `/dev/shm`) avant tout retry ou délai. Chercher d'abord dans l'historique des runs : combien de fois, sur quel runner de l'hôte de CI, à quelle charge, et si un test précédent ou un job voisin tenait la machine. Le correctif nomme la cause ; un retry ne la remplace pas.

**Blocked by:**

- External: un échec de lancement du navigateur en CI qui porte le rapport complet (après fusion de la PR 367, 5ce4e46)

**Claimed by:** (libre)

**Findings (Isolde, 2026-11-15):** Runs of 2026-10-31 to 2026-11-15 read (1000-run API cap), 273 failed jobs' logs grepped. Four cases of the skip, all on GitHub-hosted `ubuntu-24.04` (sheaf's CI does not run on the CI runner host; runner names are `GitHub Actions 10000…`, not readable from here), all image 20261111.370.1: run 43312410524 (12 Nov 21:39, test_mount_allowlist:233), 43502218938 (13 Nov 20:30, allowlist:151), 43527634386 (13 Nov 23:30, allowlist:233), 43707514947 (15 Nov 11:09, test_mount_selection:187). In each, one launch of a browser launched per test fails inside a stream of launches that pass (allowlist: one every 0.4 s; the failing one is the 9th launch at 2 %), and the next launch passes. A fifth hit of the search (run 42794285101, 10 Nov) is another cause: the Chromium executable was missing from the cache. Not established: why the browser closed; the fixtures kept only the first line of the error, and the browser's log (after that line) was dropped. Image count (partial, API limit hit): 4 failures in 192 jobs on 370.1, 0 in 307 on 360.1. Too few to name the image.
**Fix (PR 367, branch chat-box/138, Opus review GO):** `launch_engine` in tests/page/pagehelp.py: on CI a launch that fails fails the test with the whole error and the died_report; the next red run names the cause. Ticket stays open until that run.

**Status:** ready-for-agent

- [ ] Le nombre de cas et les runners sont établis à partir des runs passés
- [ ] La cause est établie dans les logs du runner, pas supposée
- [ ] Le correctif traite la cause (pas un retry ni un délai seul)
