# 73: Dictée : trois formulations du SPEC 9.16, une assertion trop large et une théorie de double fermeture, restes de la revue Opus de la PR 295 (ticket 71)

**What to build:** Les cinq constats P3 de la revue Opus de secours de la PR 295 (GO, aucun défaut a ni b), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-71-reviews/opus-1.md`. Fichiers : `SPEC.md` (9.16), `tests/test_hub_transcribe.py`, `src/sheafmd/hub/transcribe.py`.
- p1 : « no more than that is read » est trop fort : la couche texte lit 65 537 caractères plus un bloc de tampon (jusqu'à environ 256 Ko d'octets en UTF-8 multi-octets), et `\r\n` compte pour un caractère. Écrire « la lecture s'arrête juste après ».
- p2 : « reads the file three times » : ce sont trois ouvertures, chacune jusqu'à trois passes (neuf lectures au pire) ; « each read is the whole of a 0600 file » n'est plus exact, la lecture est plafonnée.
- p3 : « a chmod during a read refuses that pass » : c'est l'appel entier qui est refusé, avec la ligne unique par hub ; de même pour un fichier qui dépasse le plafond à une relecture (la ligne est alors consommée alors que l'appel suivant peut réussir). À écrire, ou à corriger si la ligne ne doit pas être consommée.
- p4 : l'assertion `"def" not in shown` de `test_a_damaged_byte_in_the_key_is_refused_the_same_way` lit toutes les lignes : elle échoue si une autre ligne contient « default » ou « undefined ». La limiter aux lignes `transcribe-key-file`, ou chercher `abc` suivi de U+FFFD.
- p5 (d'avant la PR) : si `os.fdopen` échouait après avoir construit son `FileIO`, il fermerait le descripteur lui-même et la branche `except` (`wrapped` encore faux) le fermerait une seconde fois : un numéro réutilisé par un autre fil pourrait être fermé. Aucun moyen de le déclencher trouvé (le descripteur est déjà vérifié, l'encodage est fixe). À décider : écrire ou fermer sans doute possible.

**Codex's findings on PR 295** (Nabil, 2026-11-14, `/home/tiroir/.claude/pm/chat-box-handoffs/pr-61-reviews/codex-295.md`, VERDICT NO-GO sur la PR telle que mergée) : quatre constats, tous couverts par la PR 297, aucun nouveau ticket.
- [P1] double fermeture si `os.fdopen` échoue : c'est p5. Corrigé dans la PR 297 (34a1e98) : plus de `dup`, `closefd=False`, le hub ferme une fois.
- [P2] « no more than 65,536 read » : c'est p1, écrit dans la PR 297.
- [P2] le test du chmod ne couvre qu'un chmod juste après le `fstat` d'ouverture, pas dans une passe suivante : nouveau, corrigé dans 34a1e98 (le fichier est réécrit après l'ouverture, chmod après la première passe, trois `fstat` attendus).
- [P2] l'assertion « def » lit toutes les lignes : c'est p4, corrigé dans la PR 297.
Codex sur la PR 297 (70a18f6) : trois constats (fuite du `dup`, test trop large, SPEC « après chaque lecture »), tous corrigés dans 34a1e98.

**Blocked by:** none

**Claimed by:**

**Status:** done (PR 297, merge 8bcd20b)

**Par où commencer :** `SPEC.md` 9.16 pour p1 à p3, puis p4 dans `tests/test_hub_transcribe.py`.

- [x] p1 à p3 : le SPEC 9.16 dit ce que le code fait
- [x] p4 : l'assertion limitée aux lignes de la clé
- [x] p5 décidé : corrigé avec son test (PR 297, 34a1e98)
- [x] Constats de Codex sur la PR 295 ajoutés ou écartés avec la raison
- [x] CI verte (PR 297, tête ad71cf2, 3/3 vert ; les tours Codex 1 et 2 corrigés, le tour 3 par Opus de secours : GO)
