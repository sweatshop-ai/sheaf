# 121: Deux pages écrivent le stockage des envois gardés sans relecture : fenêtre prouvée, et la conception claim/repère de la PR 341

**What to build:** Corriger la perte d'une entrée quand deux pages d'un même document font échouer un envoi au même instant (ticket 97, PR 341 réduite à la preuve). Code : `commentDraftsSave` dans `src/sheafmd/page/page.js`. SPEC 10.4 écrit la limite. Le test `test_two_sends_that_fail_at_the_same_instant_on_two_pages_are_both_kept` (`tests/page/test_page_writing.py`) est `xfail(strict=True)` : le jour où le correctif arrive, il passe et devient un échec à retirer. Les deux tests de Discard (réponse, modification) passent sur main (A n'écrit rien après le Discard de B) et fixent ce comportement pour le correctif.

**La fenêtre est prouvée.** Deux pages font échouer chacune un envoi à un instant commun (une attente active jusqu'à une heure commune dans le `fetch` de chaque page). Aux 40 tours, les deux pages lisent le même stockage (441 octets) à 0,1 ms d'écart, chacune écrit sa version (421), et la dernière remet l'entrée de l'autre encore marquée `out` : la liste « not sent » la cache pendant HELD (32 s). Relire la clé juste avant d'écrire n'aide pas : la sauvegarde la relit déjà, et la vue d'une page reste périmée bien au-delà de 100 ms (une relecture 100 ms plus tard montrait encore sa propre écriture comme la dernière).

**La conception essayée (commit ff7d176, étiquette `rashid/t97-claim-mark`, présente sur origin) :** `claim()` retient 2 s ce qu'une écriture a mis ou retiré ; `reclaim()` le revérifie à chaque événement `storage` et remet ce qu'une écriture d'une autre page a défait ; `withdrawn()` pose, avant l'écriture du stockage, un repère `<clé>:gone:<entrée>` pour tout retrait voulu (Discard, Cancel, envoi pris), et `reclaim` lâche une revendication plus ancienne que le repère. Elle ferme la fenêtre du test (40 tours verts) et le Discard, mais quatre tours de revue ont trouvé quatre a/b (voir ci-dessous) : le correctif a été laissé de côté, pas jugé faux.

**Constats des tours 1, 2 et 3** (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-97-reviews/opus-round1.md`, `r2-narrow.md`, `r3-narrow.md`) :
- a1 (tour 1) : un retrait par le hub sur une page était remis par la page qui l'avait revendiqué (réponse prise puis « not sent »). Fermé par le repère.
- Discard (tour 2, Rhea) : le Discard de B moins de 2 s après l'écriture de A était remis par A (8 écritures, main : 0). Fermé par le repère.
- C1 (tour 2) : la ligne ajoutée pour a1 annulait aussi une revendication après une écriture périmée. Retirée.
- C2 (tour 2) : une écriture de repère refusée (stockage plein) sautait l'écriture du stockage. Les repères ont leur propre `try`, la purge passe d'abord.
- F1 (tour 3, classe a, rare) : un repère refusé est avalé et le retrait est écrit quand même ; si A a écrit l'entrée moins de 2 s avant, A la remet, et B réaffiche le texte écarté. Remède proposé : quand l'écriture d'un repère échoue, sauter l'écriture du stockage seulement si elle retire quelque chose.
- F2 (tour 3, d) : aucun test ne couvre l'envoi pris par le hub sur deux pages (l'envoi de A tenu, B traite le `changed` de son rid, l'envoi de A réussit, le stockage reste sans l'entrée 3 s). La fermeture de a1 ne dépend que de l'ordre dans lequel le navigateur livre le repère et le changement du stockage.
- F3 (tour 3, c) : repères écrits puis écriture du stockage refusée : les repères restent 10 s sans que le retrait ait eu lieu.

**La leçon :** l'ordre des événements `storage` entre pages est un détail interne de Chromium. Une conception qui en dépend a besoin d'un test qui montre cet ordre (par exemple, noter l'instant de l'écriture d'un repère, de l'écriture du stockage et de l'événement chez l'autre page), avant d'être jugée fermée. Deux choses de la conception sont à décider : s'appuyer sur ces événements, ou changer de support (un verrou Web Locks, ou une entrée par clé `localStorage` au lieu d'une liste unique, qui ne se réécrase pas).

**Aussi dans ce ticket** : tout le contenu du ticket 114 (restes c et d des tours 1 et 2 : c1 à c8, d1 à d4, voir `114-restes-b-c-d-de-la-pr-341-ticket-97-reclaim-des-envois-gardes.md`) concerne cette conception ; ils ne valent que si elle est reprise. Ne rien en tirer si une entrée par clé la remplace.

**Blocked by:** aucun

**Claimed by:** Lucia

**Status:** done (PR 355, merged 0592028)

## Design note (Lucia, 2026-11-14): one `localStorage` key per entry

**Why the medium, not the events.** The race is a read-modify-write of one shared value. With one key per entry, a page writes only keys it created and removes only keys it read, so no page rewrites another page's entry; the lost write cannot happen, whatever order `storage` events arrive in. No claim, no repère, no timer.

**Key scheme.** `COMMENT_DRAFT_KEY + ':e:' + id` (that is `sheaf-comment-draft:<port>:<doc>:e:<id>`); the value is the entry's JSON, as it is today. `id` = base-36 write time, a per-page counter, 4 random characters: sorts by time then by the page's own order, never repeats across pages. Reads list the keys with that prefix, parse each, and sort by id, which keeps the list order the old array had (an entry rewritten goes last). A key whose value does not parse is skipped and left alone. The old `:unreadable` key keeps its name and is not matched by the prefix.

**Writes.** One primitive replaces `commentDraftsSave`: `draftsWrite(drop, add)`. `drop` are entries as read (each carries its key), `add` are new entries; every write has a fresh id, so nothing is ever overwritten. Callers: `draftsReplace`, `threadKeep` (drop what `goes` names, add the new entry), `taken` (drop the entry of that rid), the purge in `commentDraftsLoad` (drop what `pendingClears` names). `pendingClears` are applied again inside `draftsWrite`, so a clear that a failed purge held still goes with the next write.

**Migration of the old list key.** Any write first moves a legacy `COMMENT_DRAFT_KEY` list into entry keys, then removes the list key. The id of a migrated entry is deterministic (`0` + list position + hash of its JSON), so two pages migrating at once write the same keys and nothing doubles. An entry with no `root` takes this page's root, as a write of the old list did. A list that is not JSON is set aside under `:unreadable` first, as today. Reads (non-strict) also see a legacy list's entries without migrating, so a read never writes. Known limit: a page of an older build still open rewrites the list key; the next write of a new page migrates it again (an entry removed meanwhile can come back once). Only tabs open across the upgrade.

**How the "not sent" list and HELD read it.** Unchanged: every reader goes through `commentDraftsLoad`, which now returns the union of the entry keys and the legacy list, filtered by root and `pendingClears` as before; `inFlight` and the `out` mark are untouched. The `storage` listener redraws on any key with the entry prefix (or the legacy key, or `null`).

**Storage full.** Add first, then drop: if the add is refused, the drops are removed and the add tried once more; if it is refused again the drops are written back, `storeOk` is false and the caller is told as it is today (nothing lost that the store held). A clear (no add) only removes and cannot be refused for space. Migration that cannot be written fails the write the same way (storeOk false, nothing dropped).

**Tests.** The race test loses its `xfail`; the two Discard tests stay green; the ~30 places that read or write the old list in tests go through helpers in `pagehelp.py` (read all entries, write one). The spec pins (10.8) and SPEC 10.4/10.8 say "one key per entry".

## Close-out (Yuki, 2026-11-15)

PR 355 merged as 0592028 (head 91e8911, CI 3 of 3 green; gate: Opus fallback, GO in round 1). The race is closed by construction with one key per entry; `test_two_sends_that_fail_at_the_same_instant_on_two_pages_are_both_kept` is no longer xfail. The ticket has no checkbox list; its goal is met as follows:

- The lost entry: fixed (one `localStorage` key per entry, `draftsWrite(drop, add)`; no claim, no repère, no timer).
- The two Discard tests: green, now counting writes under the key prefix.
- SPEC 10.4/10.8 and the spec pins say "one key per entry".
- Leftovers of the review rounds (c and d): ticket 130.
- Ticket 114 (c1 to c8, d1 to d4 of the claim/repère design): the design is not taken up, and this ticket says to take nothing from them if one key per entry replaces it. It does, so 114 stands struck unless its own text says otherwise.
- Known limit, in the PR body: an old-build tab left open across the upgrade.
