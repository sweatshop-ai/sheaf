# 15: The module's name in Open WebUI

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** none
**Map:** ../map.md

## Question

The sidebar entry, the Catalog and the spec need a name a member reads. Thierry dislikes "Sheaf"; "Documents" clashes with every other document in a tiroir; "Notes" is taken by Open WebUI. Candidates from October: proof/épreuve, bon à tirer, desk, drawer. Which name does a member see in Open WebUI, in which languages, and does the tool on the laptop (`sheaf`) keep its name?

## Answer

Resolved 2026-11-15 by Ottilie with Thierry, three naming rounds (method: `glacierphonk/naming`, read from a scratch clone).

1. **The product a member sees is tiroir Recto.** It competes with Claude's Artifacts, so it is a product name inside the tiroir family, not a menu label and not a stand-alone brand (no own domain). The three ideas it carries are split over the system: *tiroir* says the pages are yours whatever model wrote them; *Recto*, the side of a sheet that faces you, is what the agent shows; the *verso* is where you answer. The line: "Your agent writes the recto. You write the verso. The drawer is yours."
2. **The verso** is the side of a page that holds its comments: a member-facing word for where the conversation with the agent lives. A comment stays a Comment; a single page stays a "page", never "a recto".
3. **One word in every language.** "Recto" reads the same in Italian, Dutch, French and English, so the sidebar entry and the title of the view say "Recto" with nothing to translate. "Catalog" stays a spec and glossary term the member never sees.
4. **`sheaf` keeps its name** for the engine, the laptop command and the repo `sweatshop-ai/sheaf`; a member in Open WebUI never sees it.

Ruled out on a competitor search in the field (AI, documents, notes): Proof (Every's proofeditor.ai, an editor for agents and humans), Margin (a beta tool commenting AI artifacts), Folio, Foyer (a client-portal document tool), Verso alone (a Mac word processor and a notes app; fine as a word inside the product), Filigrane. Drawer means tiroir. The only "Recto" found is a design-with-AI desktop app shown on Show HN, outside the field.

New terms in `GLOSSARY.md`: **Recto**, **Verso**.

## Rounds (2026-11-15, Ottilie with Thierry)

- Settled: the laptop tool, repo and engine stay `sheaf`; the name is for the product a member sees, which competes with Claude's Artifacts, so it is a marketing name, not a menu label (Thierry).
- Settled: the name lives inside the tiroir family ("tiroir X"), not a stand-alone brand; no own domain needed (Thierry).
- Method: `glacierphonk/naming` (MIT, commit e7af8a5), read from a scratch clone; installing it in `~/.claude/skills` was refused by the auto-mode classifier.
- Territories: desk objects, sheets and their sides, printing and correcting.
- Dead on competitor search: Proof (Every's proofeditor.ai, an editor for agents and humans with comments), Margin (beta tool commenting AI artifacts), Folio (five+ markdown/AI doc apps). Drawer = tiroir; Desk plants no image.
- Finalists shown to Thierry: Recto (recommended: the side facing you, comments the verso; known in it/nl/fr/en), Carnet, Calque, Sous-main; fallback "tiroir Pages".
- Open: Thierry's pick after letting them sit; then the translations of the label and whether "Catalog" stays a spec-only term.
- Round 1 rejected by Thierry (all four). Round 2 brief: the name must show "yours, not the vendor's", "exchange between agent and person" and "showing" (Thierry's pick of territories).
- Round 2 dead: Foyer (a client-portal and document-management tool launched 2026-03). Finalists shown: Salon (recommended: hits all three; nl "salon" = living room), Studiolo, Navette, Cachet (only an Estonian insurer, out of field).
- Round 2 not picked; Thierry: combine the round-2 ideas with paper, recto verso "non mi dispiaceva". Round 3 proposal: "tiroir Recto" where tiroir carries "yours", Recto "shown", and the verso (a page's comments side) "exchange". Alternatives: Vis-à-vis (facing pages), Cachet. Dead: Verso alone (a Mac word processor, a notes app, a markdown reader), Filigrane (PDF watermarking).
