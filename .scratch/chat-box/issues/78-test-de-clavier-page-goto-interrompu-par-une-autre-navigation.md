# 78: `test_page_keyboard.py::test_a_long_thread_leaves_the_field_in_reach_above_the_keyboard` échoue par intermittence dans `page.goto` : navigation interrompue par une autre navigation vers la même adresse

**What to build:** Un test de page instable vu une fois en CI sur la PR 299, sans rapport avec elle (la PR ne change que `tests/page/test_page_writing.py`).
- Test : `tests/page/test_page_keyboard.py::test_a_long_thread_leaves_the_field_in_reach_above_the_keyboard`, ligne 195, dans `phone.open()` (`tests/page/conftest.py:148`, `self.page.goto(self.site.url)`).
- Échec : `playwright._impl._errors.Error: Page.goto: Navigation to "http://127.0.0.1:23712/work/plan.md" is interrupted by another navigation to "http://127.0.0.1:23712/work/plan.md"`.
- Vu : run 43586766076, tentative 1, tranche 3/3, sur b340658 (PR 299). Les tentatives 2, 3 et 4, du même commit, sont vertes 3/3.
- Une seule observation à ce jour.

À faire : lire le journal de la tranche 3/3 de la tentative 1 du run 43586766076 (`gh api repos/sweatshop-ai/sheaf/actions/runs/43586766076/attempts/1/jobs`, puis les journaux du job). Chercher ce qui a lancé une seconde navigation vers la même adresse pendant le `goto` : la page qui se recharge d'elle-même (le test écrit le fichier juste avant d'ouvrir, `update_file`), ou un second `goto`. Cause non établie : ce n'est qu'une idée à vérifier. Reproduire en boucle sur un runner GitHub (branche jetable avec un workflow déclenché par `push`, cœurs occupés, comme au ticket 61), jamais sur le portable. Pas de correctif sans cause trouvée.

**Blocked by:** none

**Claimed by:**

**Par où commencer :** le journal du run 43586766076, tentative 1, puis `tests/page/conftest.py:148`.

- [ ] Cause trouvée (journal et reproduction)
- [ ] Le correctif traite la cause, pas un délai ni une relance
- [ ] CI verte trois fois de suite

**Status:** ready-for-agent
