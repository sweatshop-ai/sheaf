# 114: Restes b, c, d de la PR 341 (ticket 97) : reclaim des envois gardés

**What to build:** Ces restes ne valent que si la conception claim/repère du ticket 121 est reprise (la PR 341 a été réduite à la preuve, page.js égal à main). Restes de la revue Opus de la PR 341 (tours 1 et 2), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-97-reviews/opus-round1.md` et `r2-narrow.md`. Code : `claim()`/`reclaim()`/`withdrawn()` dans `src/sheafmd/page/page.js`, près de `commentDraftsSave`. Aucun b ici : les b sont corrigés dans la PR.

Classe d (tests manquants et notes) :
- d1 : pas de test pour le Discard d'un message minimisé, un Cancel de formulaire, un envoi pris par le hub (le Discard d'une réponse ou d'une modification est testé depuis la PR 341).
- d2 : le commentaire dit « par son passage » alors que la clé contient `rid` ; les affectations de `lastRead` dans `claim` et `reclaim` ne sont lues qu'après une relecture, sauf dans le cas c2.
- d4 (r3 F2) : aucun test ne couvre l'envoi pris par le hub sur deux pages : l'envoi de A tenu, B traite le `changed` de son rid, l'envoi de A réussit, le stockage reste sans l'entrée 3 s. La fermeture de a1 ne tient que par le repère.
- d3 : aucun test multi-pages n'utilise `p.clock` (voir c7).

Classe c (défauts plus petits, avec contournement) :
- c1 : deux pages qui veulent des choses opposées pour une entrée s'écrivent tour à tour (8 fois chacune) ; sur un Discard depuis la liste ouverte, chaque tour redessine le popover où la personne vient de cliquer. `reclaims` ne se remet à zéro qu'à une écriture propre : une page qui a épuisé ses 8 ne défend plus ses autres entrées.
- c2 : la purge de `pendingClears` revendique contre un `lastRead` périmé (une lecture non stricte ratée laisse `[]`) : elle revendique toutes les entrées 2 s, et pose des repères sur ce même `lastRead` (peut éteindre une revendication utile). Calculer `before` depuis la lecture brute de `commentDraftsSave`.
- c3 : une entrée sans `root` en reçoit une à l'écriture : la première écriture après une mise à jour les revendique toutes (même remède que c2).
- c4 : deux commentaires gardés sur le même passage, tous deux modifiés, perdent leur `rid` et partagent une clé ; avec une écriture périmée, `reclaim` écrase l'un par l'autre, et sans `rid` aucun repère n'est posé. Demande deux commentaires gardés modifiés sur un passage. Ajouter `at` à la clé des nouveaux commentaires.
- c5 : le `catch` de `reclaim` cache un `setItem` refusé sans mettre `storeOk = false`.
- c8 (r3 F3) : si les repères sont écrits puis l'écriture du stockage est refusée, les repères restent 10 s alors que le retrait n'a pas eu lieu : l'autre page abandonne sa revendication sur cette clé, une écriture périmée dans cette fenêtre n'est pas réparée.
- c7 : horloges factices (`p.clock`) : un repère daté du futur n'est jamais purgé par une page à l'heure réelle.

**Blocked by:** none (121 took another design; see the table)


## Check against origin/main 3bdeaf6 (Isolde, 2026-11-15)

`claim()`, `reclaim()`, `withdrawn()`, `lastRead` and the repères do not exist on main (`git grep` in `src/sheafmd/page/page.js`: none). Ticket 121 (PR 355) holds clears in `pendingClears` (page.js:1571) and writes one key per entry (`ENTRY_PREFIX`, page.js:1575, `draftsWrite` page.js:1666).

| Item | Verdict | Where on main |
|---|---|---|
| ~~c1~~ two pages rewriting in turn | struck: design withdrawn, see PR 355 | no reclaim loop; pages write their own keys, a clear is held once (page.js:1642) |
| ~~c2~~ purge claims against a stale `lastRead` | struck: design withdrawn, see PR 355 | `pendingClears` are tests applied to a strict read (page.js:1674, 1683); no `lastRead` |
| ~~c3~~ entry without `root` claimed on first write | struck: design withdrawn, see PR 355 | the root is given only to the entries a write adds or moves (page.js:1667, 1688); nothing is claimed |
| ~~c4~~ two kept comments share a key | struck: design withdrawn, see PR 355 | the key is `e:<id>`, unique per write (newEntryId, page.js:1578) |
| ~~c5~~ `reclaim` hides a refused `setItem` | struck: design withdrawn, see PR 355 | `draftsWrite` sets `storeOk = false` on a refused write (page.js:1702) and redraws the line |
| ~~c7~~ fake clock and future repères | struck: design withdrawn, see PR 355 | no repères |
| ~~c8~~ repères left after a refused write | struck: design withdrawn, see PR 355 | no repères; a refused write puts back what it read (page.js:1693-1698) |
| ~~d2~~ comment wording and `lastRead` | struck: design withdrawn, see PR 355 | the code is gone |
| ~~d3~~ no multi-page test with `p.clock` | struck: nothing to test | no repères to age |
| d4 hub-taken send on two pages | covered | test_page_writing.py `test_a_send_taken_or_cancelled_on_one_page_leaves_the_kept_reply_of_a_send_still_out_on_another` (taken and cancelled, reply and edit) |
| d1 Cancel of a form | covered | `test_cancel_of_a_form_that_was_never_sent_leaves_the_kept_text_of_a_send_out_on_another_page`, `test_cancelling_a_reply_or_edit_whose_send_failed_clears_what_it_kept` |
| d1 send taken by the hub | covered | test_page_chat_box.py `test_a_reply_the_hub_took_while_the_store_refused_reads_...` (two tests) and the d4 test above |
| d1 Discard of a minimized message | **open, one test**: page.js:1939 (`d.min` branch of `keptSendButtons`) had no test | PR 370 adds it (no code change) |

**Status:** done. The one open item (d1, Discard of a minimized message) was tested in PR 370, merged as 78c0a66; the other items are struck or covered, see the table.
