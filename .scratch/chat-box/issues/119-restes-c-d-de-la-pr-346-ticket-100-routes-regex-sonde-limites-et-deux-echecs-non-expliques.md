# 119: Restes c/d de la PR 346 (ticket 100) : routes à regex non sondées, limites de la sonde, deux échecs de CI sans cause

**What to build:** Revue Opus de la PR 346 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-100-reviews/opus-review.md` (Codex était à court de jetons). Les points de classe a et b (`times=`, `unroute(url, handler)`, handler sans paramètre, journal qui dit le contraire) sont corrigés dans la PR. Reste :

1. (c) `tests/page/test_page_work.py:295` route `re.compile(r"/_/comment$")` : une route à regex n'est pas sondée (`PROBED` ne compte que la chaîne `**/_/comment`), donc la course du ticket 100 y reste possible.
2. (c) `tests/page/conftest.py` `until_live` : toute route enveloppée répond à la sonde, quel que soit son motif ; et une route de contexte sonde `pages[0]`, ce qui ne prouve rien pour un envoi d'une autre page. Pas touché aujourd'hui (aucune route de contexte sur `/_/comment`).
3. (c) Le journal prend l'heure réelle avant que l'horloge truquée ne remplace `performance`, ce qui suppose que le script d'init du journal passe avant celui de l'horloge ; Playwright ne documente pas l'ordre. Vérifier dans un navigateur ; si l'ordre bascule, seuls les horodatages du journal sont faux.
4. (d) Le test `test_a_route_for_a_send_holds_the_send_the_page_makes_as_soon_as_route_returns` ne peut devenir rouge que sous charge : sans charge il passe avec ou sans la sonde. Ajouter un test de la sonde elle-même sur une page de remplacement (route enregistrée, première requête sondée captée).
5. (c) **Deux des trois échecs du ticket 100 ne sont pas la course de la route** : le send-again (« did not go out » vu, donc la route était vive, puis ni « New reply » ni TAKEN) et « text changed while you wrote » (a passé l'étape « the hub to take the reply »). Le journal du flux est en place ; il faut un échec réel avec lui pour dire ce qui s'est passé. Si l'un revient sur la CI, lire la section « the event stream, page and hub » du log.
6. (c) `test_page_actions.py::test_a_saved_action_box_is_not_ticked_after_a_save_answered_again` échoue à chaque tour avec trois boucles d'occupation du processeur sur un coureur à 4 cœurs (« timed out waiting for the page to reload » ; le handler de `/_/save` est appelé 2,6 s après `route()`). Pas un des trois tests du ticket 100 ; à regarder si ce test rougit sur la CI sans charge artificielle.
7. (c) `conftest.py` `noting_route` : une même fonction enregistrée deux fois sur une URL puis `unroute(url, h)` n'enlève que la seconde route (Playwright les enlève toutes les deux) ; et un handler non hachable (instance d'une classe avec `__call__`) fait lever `TypeError` à `route()`, car le handler sert de clé de dictionnaire. Aucun test ne le fait aujourd'hui.

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** le point 5 si un échec revient sur la CI avec le journal ; sinon le point 1.

- [ ] Chaque point : corrigé (test rouge d'abord quand c'est du code) ou la limite écrite dans le commentaire de `until_live`
