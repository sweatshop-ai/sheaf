# 139: Restes c et d de la PR du ticket 129 (poignée de l'upgrade et `rd-toast`)

**What to build:** Revues Opus de la branche `chat-box/129` (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-129-reviews/opus-round1.md` et `reread-after-verdict.md`).

- (c) `settle()` qui renonce (« this edit could not be merged », `page.js` ~1259) laisse `rd-toast` sans keep : sur la façade montée, le prochain boot de n'importe quel document de l'onglet le dit. Même remède que dans 129 : écrire `{doc}`.
- (c) La poignée de l'upgrade remplace le keep complet de `reloadKeep` par `{doc}` : le nouveau boot perd le défilement, le curseur, l'édition, le commentaire ouvert et la ligne « held ». Garder le keep d'origine quand son `doc` correspond.
- (c) Avec un keep `{doc}`, un `rd-press-said` stocké peut être redit par le nouveau boot, seulement si le toast d'une fusion est aussi là : à rendre cohérent avec le cas sans toast.
- (d) Une seconde fusion sur l'ancienne page après la poignée écrase le premier toast (`page.js` ~1211).
- (d) Pas de test pour un boot d'un autre document après la poignée (le filtre du boot est du code existant).

**Blocked by:** PR 129 fusionnée

**Status:** ready-for-agent
