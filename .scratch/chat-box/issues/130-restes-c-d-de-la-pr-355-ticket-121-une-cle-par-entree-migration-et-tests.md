# 130: Restes c et d de la PR 355 (ticket 121) : une clé par entrée, migration de l'ancienne liste et trous de test

**What to build:** Les restes de la revue de la PR 355 (une clé `localStorage` par entrée). Revues : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-121-reviews/opus-round1.md`, `opus-round2-narrow.md`, `opus-round3-narrow.md`. Aucun a ni b ne reste ; la PR a corrigé c2 (un effacement dans un stockage plein qui tient encore la liste d'une ancienne version).

**Classe c**
- c1 : une page à la vue périmée de l'ancienne liste refait la migration et remet une entrée qu'une autre page vient de retirer (une fois par document, à la mise à jour).
- c3 : l'identifiant d'une entrée migrée dépend de sa position dans l'ancienne liste ; un onglet d'ancienne version qui la réécrit décale les positions, et la migration suivante peut lister une entrée deux fois. Plus large que la limite écrite dans la PR. Un onglet ancien n'affiche pas non plus la ligne « not sent » après une migration.
- c4 : un document dont le chemin contient `:e:` (par exemple `a.md:e:x.md`) a des clés qui commencent par le préfixe de `a.md` : la page `a.md` liste, envoie et écarte ses réponses. Remède : vérifier la forme de l'identifiant après le préfixe.
- c5 : une écriture fait deux événements `storage` chez les autres pages (ajout puis retrait) ; entre les deux, « 2 replies not sent » peut s'afficher un instant.
- c6 : une écriture qui ajoute une entrée et s'arrête à mi-migration (stockage plein), puis un onglet ancien qui réécrit la liste avec des positions décalées : les clés restantes font des doublons ou ramènent une entrée effacée.

**Classe d**
- d1 : le test de course (`test_page_writing.py`, `test_two_sends_that_fail_at_the_same_instant...`) range les entrées par texte : il ne voit ni un doublon ni une entrée restée `out`.
- d2 : le test de l'ancien format à un seul objet (`:998`) écrit maintenant une liste par `set_kept` ; la branche « objet seul » n'est plus testée.
- d3 : rien ne couvre deux pages qui migrent en même temps, un stockage qui tient la liste et des clés d'entrée ensemble, la branche de quota où le second essai réussit (chaque simulation de stockage plein refuse tout `setItem`), une clé d'entrée qui n'est pas du JSON, ni la migration à mi-chemin et une entrée en attente (F2, F3 du tour 2).
- d4 : une clé d'entrée qui n'est pas du JSON est ignorée pour toujours, jamais mise de côté sous `:unreadable` ; le commentaire de `commentDraftsRaw` ne dit plus la vérité pour elle.
- d5 : les entrées sont triées par l'horloge de la page qui écrit ; un recul de l'horloge change l'entrée `[0]`.
- d6 : `kept_entries` (`pagehelp.py`) dit « oldest first » mais met les entrées de l'ancienne liste en dernier, la page les met en premier.
- d7 : si le retour en arrière d'une écriture refusée échoue à mi-chemin, le reste des retraits est perdu.
- d8 : deux pages qui envoient le même texte sous le même `rid` au même instant laissent deux entrées ; un Discard ou `taken` par ce `rid` retire les deux.
- d9 : l'ancienne liste réécrite plus courte (c2) revient à la course de la liste entre deux pages, seulement dans un stockage plein.

**Blocked by:** 121 (PR 355 ouverte)

**Claimed by:** Ingrid 2026-11-15 12:41

**Status:** in-progress
