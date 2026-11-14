# 96: Restes c et d de la PR 319 (ticket 70) : le filtre de style du mode simple, journal, attribut vide et tests

**What to build:** Cinq restes de la revue Opus de la PR 319 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-70-reviews/opus-1.md`), dans `src/sheafmd/sanitize.py` et `tests/test_sanitize.py`.

1. **C1.** `_without_user_modify` coupe sur chaque `;`, sans tenir compte des chaînes CSS : `content: "a;\201C"; color: red` perd `\201C"` (déclaration contenant une barre oblique inverse) et laisse un style tronqué. Rien ne passe, mais un style légitime est abîmé.
2. **C2.** Le mode simple retire des déclarations sans ligne de journal ; le mode mount écrit « style trimmed ». Écrire la même ligne.
3. **C3.** Un style vidé par le filtre reste `style=""` ; le mode mount supprime l'attribut. Faire de même.
4. **D1.** Les cas « majuscules » et « doublon » de `test_contenteditable_goes_in_any_letter_case_and_when_repeated` passent aussi sur main (html.parser met les noms en minuscules et garde un seul doublon) : ils fixent un comportement, pas ce correctif. À dire dans la docstring.
5. **D2.** Le motif `user-modify|\\` est écrit en ligne ; les autres sont compilés au niveau du module.
6. **C4 (re-lecture étroite, opus-2-narrow).** `tests/page/test_user_modify.py` n'a pas de témoin positif : un cas montrant que le span non assaini (`/*:*/…`) est bien éditable dans Chromium et WebKit. Sans lui, le test passerait pour rien si un moteur cessait d'honorer la propriété.
7. **D3.** La règle « barre oblique inverse » retire aussi des déclarations ordinaires (`content:"\201C"`) ; aucun test ne le fixe.

**Blocked by:** PR 319 fusionnée

**Status:** ready-for-agent
