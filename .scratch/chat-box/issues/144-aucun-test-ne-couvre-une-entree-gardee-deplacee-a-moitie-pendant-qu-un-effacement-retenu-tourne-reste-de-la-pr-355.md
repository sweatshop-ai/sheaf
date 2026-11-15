# 144: Aucun test ne couvre une entrée gardée déplacée à moitié pendant qu'un effacement retenu tourne (reste de la PR 355, ticket 130)

**What to build:** Le dernier trou nommé par la relecture de la PR 355 (tour 2, F2 et F3) et par le passage de Ingrid sur le ticket 130 (PR 369) : aucun test ne couvre le cas où le déplacement de la liste d'un build plus ancien vers des clés d'entrée s'arrête à mi-chemin (stockage plein) pendant qu'un effacement retenu (`pendingClears`, `page.js`) est joué par la première lecture qui marche. Le chemin est `draftsWrite`, branche `catch` de `migrateDrafts` : il enlève les clés déjà faites, calcule `goes` avec `drop` et `pendingClears`, et réécrit la liste.

**Blocked by:** none

**Claimed by:** Bodil 2026-11-15

**Status:** in-progress

**Par où commencer :** `tests/page/test_page_kept_entries.py`. Une liste de trois entrées sous la clé ; le store refuse la lecture pendant qu'on écarte l'une (l'effacement est retenu) ; le store ne laisse plus faire qu'une clé ; la première lecture qui marche joue l'effacement. Attendu : l'entrée écartée ne revient pas, les deux autres sont là une seule fois, aucune clé d'entrée à moitié faite ne reste. Test sur t-compute, jamais sur le portable. S'il est rouge, c'est un vrai bogue : cause, puis correction, test d'abord.

- [ ] Un test couvre une liste déplacée à mi-chemin avec un effacement retenu ; vert (verrou) ou rouge puis corrigé
