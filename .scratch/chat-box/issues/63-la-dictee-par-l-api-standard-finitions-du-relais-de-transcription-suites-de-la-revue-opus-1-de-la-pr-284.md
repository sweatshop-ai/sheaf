# 63: Dictée (API standard) : finitions du relais de transcription, suites de la revue Opus 1 de la PR 284

**What to build:** Constats de classe c et d de la revue Opus 1 de la PR 284 (GO, aucun défaut a ni b), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-06c-reviews/opus-1.md`, et de la relecture Opus 2 (`opus-2-narrow.md`, GO). Non corrigés dans la PR. Tous dans `src/sheafmd/hub/transcribe.py` (numéros de ligne de 465b442, à relire). Classe c et d, à décider un par un : corriger, ou écrire la limite dans le SPEC.
- c2 (:214-227) Ordre fstat/lecture : un écrivain qui termine entre les deux donne (ancien cachet, nouvelle clé). Si cette clé est refusée, `_stay_off` garde l'ancien cachet, le prochain `available()` voit le nouveau et lève l'arrêt : un appel refusé de plus. Inoffensif. À faire : relire le cachet (fstat) après la lecture, ou fstat sur le même descripteur après `read`.
- c3 (:272-277) Deux dictées en file peuvent envoyer chacune une clé refusée : `available()` est testé avant le verrou ; une seconde requête qui l'a passé pendant que la première était en vol, et prend le verrou après son 401, renvoie la même clé au même hôte une fois de plus. Même hôte, pas de fuite, un appel perdu. À faire : retester `_stay_off` après avoir pris le verrou.
- c4 (:221, :172) Une clé non latin-1 (ou un octet abîmé devenu U+FFFD par `errors="replace"`) fait lever `http.client` dans `putheader` ; `_call` l'avale comme statut 0, la ligne dit « no answer » et le bouton revient toutes les 30 s. Le texte de la ValueError contient la clé mais n'est jamais journalisé (vérifié). Seul le diagnostic est trompeur. À faire : refuser la clé non latin-1 à la lecture avec un motif dans `transcribe-key-file`, sans la citer.
- c5 (:123-124) La confiance TLS vient de `ssl._create_default_https_context` (défaut de http.client). Rien dans src/ ne le remplace, mais toute bibliothèque importée qui le fixerait à `_create_unverified_context` enverrait la clé Bearer sur du TLS non vérifié. À faire : passer `context=ssl.create_default_context()` explicitement.
- d4 (la fixture de test est sans lignes PEM depuis f07bf86) : rien à faire, à clore.
- Notes de la relecture 2 : le docstring de `_key` (:205) dit « mtime, ctime » alors que le code stocke les champs `_ns` (d) ; le docstring de `available()` (:236-238) ne dit pas qu'un changement de métadonnées seul (chmod, touch) lève aussi l'arrêt pour une tentative de plus, une seule requête vers l'hôte `url`, comptée par `_spend()` (c).

**Blocked by:**
- External: PR 284 merged into main

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** `tests/test_hub_transcribe.py` : un test par point (c3 : deux requêtes concurrentes, une seule clé refusée envoyée ; c4 : clé non latin-1 refusée avec motif, sans la clé dans le journal ; c5 : le contexte passé est un contexte vérifiant ; c2 : une écriture entre fstat et lecture ne laisse pas l'ancien cachet avec la nouvelle clé).

- [ ] c2, c3, c4, c5 corrigés ou la limite écrite dans le SPEC 4.3 / 9.16, chacun avec son test
- [ ] Les deux docstrings de la relecture 2 disent ce que fait le code
- [ ] CI verte
