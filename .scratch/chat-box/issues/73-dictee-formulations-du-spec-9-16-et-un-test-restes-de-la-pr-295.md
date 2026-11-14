# 73: Dictée : trois formulations du SPEC 9.16, une assertion trop large et une théorie de double fermeture, restes de la revue Opus de la PR 295 (ticket 71)

**What to build:** Les cinq constats P3 de la revue Opus de secours de la PR 295 (GO, aucun défaut a ni b), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-71-reviews/opus-1.md`. Fichiers : `SPEC.md` (9.16), `tests/test_hub_transcribe.py`, `src/sheafmd/hub/transcribe.py`.
- p1 : « no more than that is read » est trop fort : la couche texte lit 65 537 caractères plus un bloc de tampon (jusqu'à environ 256 Ko d'octets en UTF-8 multi-octets), et `\r\n` compte pour un caractère. Écrire « la lecture s'arrête juste après ».
- p2 : « reads the file three times » : ce sont trois ouvertures, chacune jusqu'à trois passes (neuf lectures au pire) ; « each read is the whole of a 0600 file » n'est plus exact, la lecture est plafonnée.
- p3 : « a chmod during a read refuses that pass » : c'est l'appel entier qui est refusé, avec la ligne unique par hub ; de même pour un fichier qui dépasse le plafond à une relecture (la ligne est alors consommée alors que l'appel suivant peut réussir). À écrire, ou à corriger si la ligne ne doit pas être consommée.
- p4 : l'assertion `"def" not in shown` de `test_a_damaged_byte_in_the_key_is_refused_the_same_way` lit toutes les lignes : elle échoue si une autre ligne contient « default » ou « undefined ». La limiter aux lignes `transcribe-key-file`, ou chercher `abc` suivi de U+FFFD.
- p5 (d'avant la PR) : si `os.fdopen` échouait après avoir construit son `FileIO`, il fermerait le descripteur lui-même et la branche `except` (`wrapped` encore faux) le fermerait une seconde fois : un numéro réutilisé par un autre fil pourrait être fermé. Aucun moyen de le déclencher trouvé (le descripteur est déjà vérifié, l'encodage est fixe). À décider : écrire ou fermer sans doute possible.

Codex doit encore passer sur la PR 295 (sans jetons le 2026-11-14 jusqu'à 15 h) : ses constats s'ajoutent ici.

**Blocked by:** none

**Claimed by:**

**Status:** ready-for-agent

**Par où commencer :** `SPEC.md` 9.16 pour p1 à p3, puis p4 dans `tests/test_hub_transcribe.py`.

- [ ] p1 à p3 : le SPEC 9.16 dit ce que le code fait
- [ ] p4 : l'assertion limitée aux lignes de la clé
- [ ] p5 décidé : écrit, ou corrigé avec son test
- [ ] Constats de Codex sur la PR 295 ajoutés ou écartés avec la raison
- [ ] CI verte
