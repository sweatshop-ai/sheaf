# 60: Restes de la revue Opus de la PR 280 : l'instantané lu puis publié sans verrou, le journal écrit avant le fichier, le remplissage de `agent`

**What to build:** Sept trouvailles de classe c (cas tirés par les cheveux) de `pr-40-reviews/opus-round1.md`, sorties de la PR 280 (tickets 40 et 41) selon la règle de la piste. Aucune n'est reproduite. À prendre ensemble si l'une est prise.

1. **F1** : `live.py:212` lit l'instantané, `live.py:214` le publie, et `Waiting._lock` n'est pas tenu entre les deux : un `take` peut écrire et publier `tell-seen` dans cet intervalle. `/_/doc` (`handler.py:835`) a le même intervalle. La SPEC 9.8 le dit maintenant.
2. **F3** : une ancienne ligne sans `agent`, lue par un instantané `sweep=False` avant le premier `_change`, montre le nom du jeton (`ada-chatgpt`) au lieu du nom signé, environ un tour du veilleur après le démarrage.
3. **F4** : `if save or filled:` fait écrire des passes qui n'écrivaient rien ; si le dossier d'état n'est pas inscriptible alors qu'une ancienne ligne existe, chaque tour du veilleur échoue.
4. **F5** : les lignes du journal de diagnostic sont encore écrites dans `change`, avant l'écriture du fichier (`Refused` dans `queue`, ou écriture ratée) ; le docstring du module dit que le journal est d'accord, ce qui est faux pour lui.
5. **F6** : le refus 409 de `queue` nomme l'agent par son nom courant, la ligne de la page par le nom gardé.
6. **F7** : cas limites du remplissage : un `agent` présent mais vide n'est jamais rempli ; un jeton sans client écrirait `agent: ""`.

**Blocked by:** none

**Status:** open

**Établi (preuves) :** lecture seule de l'Opus, tour 1 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-40-reviews/opus-round1.md`), avec citations. Non reproduit.

- [ ] Chaque point est soit corrigé avec un test rouge, soit écarté avec la raison
