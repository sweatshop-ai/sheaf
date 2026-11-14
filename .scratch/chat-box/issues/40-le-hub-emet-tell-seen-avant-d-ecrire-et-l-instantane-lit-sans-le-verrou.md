# 40: `waiting.take` publie `tell-seen` avant d'écrire `tells.json`, et l'instantané des attentes lit le fichier sans le verrou

**What to build:** Reste du ticket 23 (paragraphe « À regarder », revue Opus du 2026-11-11), séparé du ticket 23 parce qu'il touche l'ordre des écritures du hub et non le nom de l'agent. Dans `src/sheafmd/hub/waiting.py`, `take` appelle `_emit("tell-seen", …)` dans la fonction `change`, avant que `_change` écrive le fichier ; `waits()` lit `tells.json` sans le verrou des attentes (`waiting.py` autour des lignes 220 et 261, appelé par `core.py:484`, `live.py:183`, `mcp.py:636`). Un instantané pris entre l'émission et l'écriture peut dire « queued » juste après `tell-seen` et remettre la ligne de la page à « en attente » jusqu'au prochain événement. Classe : c (course, pas reproduite).

**Blocked by:** none

**Claimed by:** Isolde 2026-11-13 23:53

**Status:** done (PR 280, merge 062f3a5)

**Établi (preuves) :** relu par la revue Opus du tour 1 du ticket 23 (`pr-23-reviews/opus-round1.md`) : les deux moitiés sont encore vraies sur chat-box/23 (bbf4dbe). Aucun test ne pose la fenêtre.

**Par où commencer :** émettre après l'écriture (par exemple collecter les événements dans `change` et les publier quand `_change` a écrit), et lire `tells.json` sous le verrou dans `waits()`, sans tenir le verrou du document (le commentaire de `waits` dit pourquoi : verrou du document et de l'admission).

- [x] Un test pose la fenêtre à la main (un instantané pris entre l'émission de `tell-seen` et l'écriture) et échoue sans le correctif — `tests/test_hub_waiting.py::test_tell_seen_goes_out_only_after_tells_json_holds_the_seen_row` et `::test_a_snapshot_asked_while_the_listing_writes_waits_for_it_and_never_says_queued_after_tell_seen` (rouges avant le correctif, 6df597d)
- [x] `tell-seen` n'est publié qu'après l'écriture ; `waits()` ne lit pas un fichier à moitié remplacé — `_change` retient les événements et les envoie après `write_json`, toujours sous les deux verrous ; `waits()` lit sous le verrou de fil (pas celui du document). Le fichier n'est jamais à moitié écrit (`write_text_private` : écriture complète puis `os.replace`) ; ce que le verrou garantit, c'est qu'un instantané ne précède pas une écriture dont l'événement est déjà parti
- [x] Les tests de la page (CI) restent verts — PR 280, tête 60f23be : total_count 3, trois tranches success (la tête finale ajoute la fusion de 4b62ad3)
