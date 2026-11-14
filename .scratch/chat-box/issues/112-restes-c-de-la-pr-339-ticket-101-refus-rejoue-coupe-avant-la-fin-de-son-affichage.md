# 112: Restes c de la PR 339 (ticket 101) : un refus rejoué encore affiché n'est plus porté par un rechargement tardif

**What to build:** Revue Opus de la PR 339 : `/home/tiroir/.claude/pm/chat-box-handoffs/pr-101-reviews/opus-round1.md`, point 2 (classe c). Le refus rejoué est mis en file derrière le toast du rechargement (2,6 s, `page.js` ~4481) puis affiché 7 s, mais il est porté jusqu'à l'échéance d'origine. Un second rechargement dans les ~2,6 dernières secondes de cette échéance, ou après, lâche un refus que le lecteur a encore sous les yeux. Le SPEC 10.11 le couvre par « l'échéance est celle sous laquelle il a été dit d'abord ». Décider : garder la limite (la dire en une phrase, avec l'exemple) ou porter le refus tant qu'il est à l'écran sans le laisser s'enchaîner (échéance d'origine + durée de la file au plus, à borner par un test rouge d'abord).

Aussi, de la relecture r2 (`pr-101-reviews/r2-narrow.md`) :
- (c) `page.js` ~4448 : `rd-keep` est lu par `JSON.parse` dans le `try` du démarrage avant les `removeItem` ; une valeur non JSON casserait chaque chargement comme le faisait `rd-press-said`. Retirer toutes les clés avant les deux lectures. Rien n'écrit un autre format aujourd'hui.
- (d) `tests/page/test_page_actions.py` ~401 : « refus non redit » ne peut pas échouer, le test ne pose pas de `rd-keep`, et la garde `&& keep` écarte déjà le refus. Poser un `rd-keep` valide pour ce document.

**Blocked by:** PR 339 merged

**Claimed by:** Malik

**Status:** ready-for-agent

**Par où commencer :** `tests/page/test_page_actions.py`, le test du refus qui n'est plus rejoué après ses 7 secondes ; sur t-compute, jamais sur le portable.

- [ ] Limite écrite dans le SPEC, ou refus porté tant qu'il est affiché, test rouge d'abord
