# 50: `threadKeep` et `taken()` perdent un effacement quand la lecture du stockage est refusée : une réponse que le hub a prise peut redevenir « not sent » et inviter un doublon

**What to build:** Dans `src/sheafmd/page/page.js`, `threadKeep` (annuler une réponse ou une modification, jeter une entrée gardée, nettoyer après un envoi réussi) et `taken(rid)` retirent une entrée du stockage des brouillons. Quand la lecture est refusée, `threadKeep` rend la main sans rien garder (`if (!ds) return;`) et `taken` lit `[]` : l'effacement est oublié. L'entrée écrite à l'envoi (avec `out`) reste dans le stockage ; une fois `HELD` écoulé, la réponse que le hub a pourtant acceptée est offerte comme « not sent » et peut être envoyée une seconde fois. Le ticket 30 (PR 263) a réglé le cas du champ d'un nouveau message vidé (`draftsReplace` sans `add` garde l'effacement dans `pendingClears`). Le ticket demande la même garde pour ces deux écrivains : garder l'effacement (un test sur l'entrée à retirer) et le tenir hors des lectures de la page jusqu'à la prochaine écriture qui aboutit.

**Blocked by:** none

**Établi (preuves) :** revue Opus de la PR 263 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-30-reviews/opus-fallback.md`, P2) : lecture du code seulement, `page.js` autour de `threadKeep` (appels à la suite d'une réponse acceptée et d'une modification) et de `taken`. Non reproduit par un test.

**Par où commencer :** un test de page : une réponse envoyée dont l'entrée gardée porte `out`, le stockage qui refuse la lecture au moment où le hub l'accepte (`store_unreadable` dans `tests/page/test_page_chat_box.py`), la lecture rétablie, `HELD` écoulé : l'entrée ne doit pas apparaître dans la ligne « not sent ». Il échoue tant que l'effacement est oublié. Réutiliser `pendingClears` du ticket 30 plutôt qu'un second mécanisme.

- [ ] Un test de page échoue tant qu'une réponse acceptée par le hub, effacée pendant une lecture refusée, revient comme « not sent »
- [ ] Même garde pour `taken(rid)` : un test avec un `changed` reçu pendant une lecture refusée

**Claimed by:** Naya 2026-11-13 23:53

**Status:** in-progress
