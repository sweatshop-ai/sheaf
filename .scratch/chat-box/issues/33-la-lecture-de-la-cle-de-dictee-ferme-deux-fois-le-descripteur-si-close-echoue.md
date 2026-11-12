# 33: `transcribe.py` `_key` ferme deux fois le descripteur si `os.close` échoue sur un fichier qui n'est pas régulier

**What to build:** Dans `src/sheafmd/transcribe.py`, fonction `_key` (ligne 122 avec les lignes 132-134), la branche « pas un fichier régulier » appelle `os.close(fd)` à l'intérieur du `try` alors que `wrapped` vaut encore `False`. Si ce `close` lève `OSError` (par exemple un EIO au flush d'un FUSE), le `except` ferme le même numéro de descripteur une seconde fois : EBADF, réponse 500 sans ligne de diagnostic, et sur un hub à fils le second `close` peut fermer le descripteur d'un autre fil. Classe : c (trouvé au tour 4 de la PR #248, ticket 06a, vérifié par lecture ; hors du correctif du tour 3).

**Blocked by:** none

**Établi (preuves) :** `codex-round4.md` du tour 4 (Opus, delta a383307..ae1dae2), constat [c], marqué VERIFIED. Non reproduit par un test.

**Par où commencer :** mettre `wrapped = True` avant le `close` de cette branche, ou sortir le `close` du `try`. Le descripteur est alors fermé une seule fois par celui qui le possède, quel que soit le chemin.

- [ ] Un test fait lever `OSError` à `os.close` dans la branche « pas un fichier régulier » et échoue sans le correctif (descripteur fermé deux fois)
- [ ] Le descripteur est fermé une seule fois sur chaque chemin ; l'échec de lecture donne `available: false` et une ligne de diagnostic `transcribe-key-file`, jamais un 500
- [ ] Aucune clé dans le test, le dépôt ni les journaux

**Claimed by:** Greta 2026-11-13 00:16

**Status:** in-progress
