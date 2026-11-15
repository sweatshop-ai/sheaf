# 15: The module's name in Open WebUI

**Type:** grilling
**Status:** claimed by Ottilie (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

The sidebar entry, the Catalog and the spec need a name a member reads. Thierry dislikes "Sheaf"; "Documents" clashes with every other document in a tiroir; "Notes" is taken by Open WebUI. Candidates from October: proof/épreuve, bon à tirer, desk, drawer. Which name does a member see in Open WebUI, in which languages, and does the tool on the laptop (`sheaf`) keep its name?

## Work in progress (2026-11-15, Ottilie with Thierry)

- Settled: the laptop tool, repo and engine stay `sheaf`; the name is for the product a member sees, which competes with Claude's Artifacts, so it is a marketing name, not a menu label (Thierry).
- Settled: the name lives inside the tiroir family ("tiroir X"), not a stand-alone brand; no own domain needed (Thierry).
- Method: `glacierphonk/naming` (MIT, commit e7af8a5), read from a scratch clone; installing it in `~/.claude/skills` was refused by the auto-mode classifier.
- Territories: desk objects, sheets and their sides, printing and correcting.
- Dead on competitor search: Proof (Every's proofeditor.ai, an editor for agents and humans with comments), Margin (beta tool commenting AI artifacts), Folio (five+ markdown/AI doc apps). Drawer = tiroir; Desk plants no image.
- Finalists shown to Thierry: Recto (recommended: the side facing you, comments the verso; known in it/nl/fr/en), Carnet, Calque, Sous-main; fallback "tiroir Pages".
- Open: Thierry's pick after letting them sit; then the translations of the label and whether "Catalog" stays a spec-only term.
