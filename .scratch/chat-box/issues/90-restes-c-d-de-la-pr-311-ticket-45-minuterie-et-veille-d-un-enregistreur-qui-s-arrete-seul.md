# 90: Restes c/d de la PR 311 (ticket 45) : minuterie et veille d'un enregistreur qui s'arrête seul, et détails de test

**What to build:** Restes de la revue Opus de la PR 311 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-45-reviews/review-1.md`), aucun de classe a ou b.

- **(c)** Un `MediaRecorder` qui s'arrête sans `stopDictation` (piste du micro débranchée, erreur de l'enregistreur) : son gestionnaire `stop` libère `dict` mais ne fait ni `clearTimeout(d.timer)` ni `clearInterval(d.watch)`. Jusqu'à 120 s plus tard, `d.timer` appelle `stopDictation(false)` sur le `dict` courant : un nouvel enregistrement est coupé et envoyé trop tôt. Hors montage, `d.watch` interroge `/_/transcribe` toutes les 15 s pour la vie de la page (et `unmount` ne le nettoie pas). Correctif : nettoyer les deux dans le gestionnaire `stop`, et faire tester `dict === d` à la minuterie avant `stopDictation(false)`.
- **(d)** Le faux micro répond à la deuxième demande aussitôt ; ce que fait un vrai navigateur d'une deuxième demande pendant une invite ouverte n'est pas exercé.
- **(d)** La branche « refus d'une invite périmée » (silence) n'a pas de test : le faux micro doit pouvoir rejeter une demande tenue (`mic.refuse`).
- **(d)** Le `stop()` du faux enregistreur émet `stop` de façon synchrone ; l'intervalle où `dict` est nul avant l'événement `stop` n'est pas exercé (théorique : un envoi qui échoue et rend la forme avant l'événement `stop` de l'ancien enregistreur).
- **(d)** Le commentaire au-dessus de `dict` (page.js, « until its answer is in ») ne dit pas que `dict` est vidé dès l'abandon.

**Blocked by:** PR 311

**Claimed by:** Perla 2026-11-14 18:51

**Status:** done (PR 326, merge 20b24c7)
