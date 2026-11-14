# 108: Restes d de la PR 334 (ticket 91) : `import json` dans `reopen_reads`, et passage Codex dû

**What to build:** Reste de la revue Opus de la PR 334 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-91-reviews/review-1.md`), aucun de classe a, b ou c.

- **(d)** `tests/page/test_page_chat_box.py` :483 : `import json` dans `reopen_reads`. Le fichier le fait déjà dans d'autres fonctions (:410 et autres) ; à remonter en tête du fichier d'un coup, avec les autres.
- **Passage Codex dû** : la revue de la PR 334 est celle d'un agent Opus (Codex sans jetons jusqu'au 2026-11-15 01:00). Le passage Codex se fait après le retour de Codex ; ses trouvailles sont des tickets, pas un revert (voir ticket 107).

**Blocked by:** PR 334

**Claimed by:** Xavier

**Status:** ready-for-agent
