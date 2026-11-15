# 134: Restes c/d du ticket 119 : regex liée à l'origine, tests sans navigateur sous la marque page, deux échecs de CI sans cause

**What to build:** Revue Opus de la branche chat-box/119 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-119-reviews/opus-review.md` (GO, aucun P1/P2). Les deux P3 de documentation et de test qui bloquent (docstring de `until_live`, deux tests qui se bloquaient au lieu d'échouer) sont corrigés. Reste :

1. (d) Les tests de `until_live` avec une page de remplacement (`ReplacementPage`) n'ont pas besoin de navigateur, mais `test_page_waits.py` porte `pytestmark = page` et `importorskip("playwright")` : `-m "not page"` les saute. Les mettre dans un fichier sans la marque.
2. (c) Une route à regex liée à l'origine du hub n'est pas sondée sur une page d'une autre origine (page d'accueil d'un montage). Aucun test ne le fait aujourd'hui.
3. (d) Les tests « deux fois routé » et « handler non hachable » étaient rouges avant le correctif ; les tests de la sonde avec la page de remplacement et celui de l'horloge du journal fixent un comportement qui existait déjà (le message de commit 7597de6 dit « red » pour tous : inexact).
4. (c) **Toujours sans cause : les deux échecs du ticket 100** (send-again ; « text changed while you wrote ») et le test de la PR 344 (« page did not answer »). Aucun log de CI avec le journal du flux n'a été vu. Si l'un revient, lire la section « the event stream, page and hub » du log. Le ticket 100 reste ouvert tant que ce point l'est.

**Blocked by:** PR 346 (ticket 100) et la PR du ticket 119 fusionnées.

**Claimed by:** Isolde 2026-11-15 00:12

**Status:** done: merged as 8654d8c (PR 362)

**Résultat, point par point :**
1. Corrigé : `tests/page/test_route_probe.py`, sans la marque `page` (2 passed avec `-m "not page"`).
2. Limite connue, écrite dans la docstring de `until_live` : une regex liée à l'origine du hub n'est pas sondée sur une page d'une autre origine ; aucun test ne le fait, la réparer demanderait de choisir l'origine de la sonde pour rien.
3. Limite connue : le message du commit 7597de6 dit « red » pour tous les tests alors que trois seulement l'étaient (regex, deux fois routé, non hachable : vérifié un par un sur l'ancien conftest, avec `timeout`) ; le commit est poussé, pas réécrit. Les trois autres fixent un comportement existant.
4. → ticket 137 (les échecs sans cause ; Chromium qui ne démarre pas : ticket 138).
Le blocage : « deux fois routé » restait suspendu sur l'ancien code (le fetch tenu par une route jamais répondue). Le handler abandonne maintenant la route et le fetch est borné par `stalls_after(10)` : une régression donne un échec, pas un gel.

- [x] Chaque point : corrigé (test rouge d'abord quand c'est du code) ou la limite écrite
