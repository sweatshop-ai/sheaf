# 77: `test_hub_upgrade.py::test_sheaf_stop_of_a_service_hub_exits_stopped_and_the_supervisor_leaves_it_down` échoue par intermittence (`assert 0 == 3`)

**What to build:** Un test instable vu une fois en CI sur la PR 300, sans rapport avec elle (le commit touchait `comments.py`, `SPEC.md` et deux fichiers de tests).
- Test : `tests/test_hub_upgrade.py::test_sheaf_stop_of_a_service_hub_exits_stopped_and_the_supervisor_leaves_it_down`.
- Échec : `AssertionError: assert 0 == 3`, run 43588278884 (workflow CI, commit ecd6369, tranche 3/3 : 1 failed, 2762 passed, 4 skipped en 123,99 s, le 2026-11-14 vers 11:06 UTC).
- Le commit suivant (e846906) et le suivant (190bc94) ont passé 3/3 sans rien changer à ce test ; la tranche n'a pas été relancée.
- Ce n'est pas le test instable du ticket 61 (`test_page_writing.py:2658`).

À faire : lire le journal de la tranche 3/3 du run 43588278884 (`gh api repos/sweatshop-ai/sheaf/actions/runs/43588278884/jobs`), trouver ce que `0` et `3` comptent (code de sortie, nombre de lancements du superviseur ?), reproduire sur le serveur auto-hébergé (pas sur le portable) en boucle, puis corriger la condition de course ou borner l'attente. Pas de correctif sans cause trouvée.

**Blocked by:** none

**Claimed by:** Zara

**Par où commencer :** le journal du run 43588278884, puis le test dans `tests/test_hub_upgrade.py`.

- [x] Cause trouvée (journal et reproduction). `cli.main(["stop"])` tournait dans le processus du test, dont le hub est l'enfant ; `sheaf stop` finit par `hubclient.ended()` -> `signals.reap()` -> `os.waitpid(WNOHANG)`, qui reape le hub et jette son code ; `Popen.wait` (thread du Supervisor) reçoit alors ChildProcessError et rend 0, pas `EXIT_STOPPED` (3). Reproduit sur le serveur auto-hébergé : 1 échec sur 600 passages, même `assert 0 == 3`.
- [x] Test corrigé : `sheaf stop` tourne dans un sous-processus (PR 304). 0 échec sur 600 passages sur le serveur auto-hébergé. Revue Opus tour 1 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-77-reviews/review-1.md`) : pas de a, b1 corrigé, c et d au ticket 84.
- [x] CI verte trois fois de suite : run 43597332024, tentatives 1, 2, 3, tête d2a876e, trois tranches vertes.

**Status:** done (PR 304 fusionnée, main f4c75d3, 2026-11-14 ; restes au ticket 84)
