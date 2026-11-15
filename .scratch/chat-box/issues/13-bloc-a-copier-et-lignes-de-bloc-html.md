# 13: Bloc à copier : une ligne qui ouvre un bloc HTML avant `---` rend le bloc en citation simple

**What to build:** Un bloc `> [!COPY]` dont le premier paragraphe est suivi d'une ligne ouvrant un bloc HTML (`<div>`, `<!-- x -->`, `<pre>`) puis d'un `---` ou `===` doit être reconnu comme bloc à copier, avec son bouton Copier. Issu de la 4e passe Opus de la PR #240 (P2 écarté) : https://github.com/sweatshop-ai/sheaf/pull/240#issuecomment-6783899357

**Blocked by:** none

**Status:** done — on main via 5767d19 (PR 289), les quatre cases ; les restes de classe c au ticket 69

**Ce qui ne va pas :** `copyblock.py`, `_OPENS_BLOCK` (`is_copy_block`). Pour GFM, une ligne qui ouvre un bloc HTML termine le paragraphe du marqueur ; l'expression régulière ne la connaît pas et lit le `---` suivant comme un soulignement de titre. Le bloc s'affiche alors comme une citation simple dont le texte est `[!COPY]`, sans bouton. Les décalages des commentaires restent justes (ils sont lus dans l'arbre de pandoc) : le défaut échoue sans danger, c'est une fonction manquante, pas un texte corrompu. Exemple : `> [!COPY]` / `> a` / `> <div>` / `> ---`.

- [x] Le bloc de l'exemple s'affiche avec son bouton Copier, et sa sauvegarde garde le marqueur
- [x] Test qui reproduit le cas (avec `<div>`, `<!-- x -->` et `<pre>`), rouge avant le correctif
- [x] Les cas déjà couverts par `tests/test_copy_blocks.py` passent toujours, dont ceux où `---` souligne vraiment le premier paragraphe
- [x] PR séparée, CI verte
