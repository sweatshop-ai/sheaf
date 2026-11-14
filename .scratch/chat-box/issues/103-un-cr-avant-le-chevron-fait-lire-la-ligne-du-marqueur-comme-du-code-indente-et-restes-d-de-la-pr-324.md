# 103: Un CR avant le `>` de la ligne `[!COPY]` : le découpeur y voit du code indenté, le bouton Copier est perdu (restes de la PR 324)

**What to build:** Reste c1 de la 2e relecture étroite de la PR 324 (ticket 94), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-94-reviews/opus-2-narrow.md`. Un CR avant le `>` de la ligne marqueur (`   \r> [!COPY]`, `\r\r\r   > [!COPY]`) : `split_md_blocks` compte le CR comme indentation et classe la ligne `indented_code`, donc `hide` ne voit jamais de citation ; pandoc supprime le CR et lit une citation. Page : pas de bouton, marqueur en texte. Sens nuisible, mais n'est atteint que par les chemins qui lisent le texte brut (sauvegarde et commentaires du hub). 168 cas sur 3586, identiques avant et après la PR 324. Correctif attendu dans `blocks.py` : le compte d'indentation saute les `\r`. Test rouge d'abord, mesuré contre pandoc 3.9.

**Restes d (PR 324) :**
- le `\r?` du lookahead de `_LINE` ne peut plus rien reconnaître (les deux appelants passent une ligne sans CR) : le retirer.
- le test de la ligne marqueur ne vérifie que l'échange par `hide`, pas le HTML après `mark` (la sonde de la relecture le couvre) : ajouter une assertion sur `mark`.

**Blocked by:** none

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] Test rouge puis vert pour le CR avant le `>`, mesuré contre pandoc 3.9
- [ ] Les deux restes d réglés
