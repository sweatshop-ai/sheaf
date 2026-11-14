# 71: Dictée : restes de la revue Opus 1 de la PR 290 (ticket 63), classes c et d

**What to build:** Constats de classe c et d de la revue Opus 1 de la PR 290 (GO, aucun défaut a ni b), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-63-reviews/opus-1.md`. Tous dans `src/sheafmd/hub/transcribe.py` et `tests/test_hub_transcribe.py`. À décider un par un : corriger, ou écrire la limite.
- c1 (corrigé dans la PR 290, commit 0af8489) : l'assertion de fuite de `test_a_key_the_header_cannot_carry_is_refused_with_a_reason_and_never_quoted` était vide (`json.dumps` échappe le non-ASCII) ; elle lit maintenant avec `ensure_ascii=False`. À vérifier : la rendre rouge en faisant écrire la clé dans une ligne, puis revenir.
- d1 : la branche « le fichier change encore après 3 lectures » (`for ... else: return None` de `_key`) n'a pas de test.
- d2 : le contrôle du mode et du propriétaire se fait une fois, avant la boucle de lecture ; un chmod à 0644 pendant la lecture change le ctime, le fichier est relu, mais le nouveau mode n'est pas revérifié (la clé de cette passe est utilisée, le prochain appel refuse). Pas de nouvelle exposition. À faire : refaire le `fstat` avec le contrôle de mode à chaque passe, ou écrire la limite.
- d3 : `test_a_damaged_byte_in_the_key_is_refused_the_same_way` ne vérifie que l'existence d'une ligne `transcribe-key-file` : ni que le motif nomme latin-1, ni que `abc`/`def` en sont absents.
- d4 : une dictée lit le fichier de clé trois fois (deux `available()`, un `_key()`), le prix de c3. Inoffensif ; à clore ou à fusionner en une lecture.
- d5 : le contexte propre à `create_default_context()` perd l'ALPN `http/1.1` que http.client ajoute ; sans effet. Il honore `SSL_CERT_FILE` / `SSL_CERT_DIR` de l'environnement du hub, même frontière de confiance : à écrire dans le SPEC 9.16, sans code.
- d6 (d'avant la PR) : `_key` lit tout le fichier sans plafond de taille, jusqu'à trois fois ; fichier du propriétaire du hub, mode 0600. À faire : plafonner la lecture.

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** `tests/test_hub_transcribe.py` : d1 (un fichier qui change à chaque `fstat` rend `_key` à None sans lever), puis d3 et c1.

- [ ] c1 vérifié rouge, d1, d3 : tests
- [ ] d2, d6 corrigés ou la limite écrite dans le SPEC 9.16, avec leur test
- [ ] d4, d5 : closes ou écrites dans le SPEC 9.16
- [ ] CI verte
