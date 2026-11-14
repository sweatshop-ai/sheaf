# 95: `blocks.ATX_RE` utilise `\s` : le découpeur coupe une citation là où pandoc garde le paragraphe (restes de la PR 324)

**What to build:** Reste c de la relecture de la PR 324 (ticket 94), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-94-reviews/opus-1.md`. `blocks.ATX_RE = ^\s{0,3}#{1,6}(\s|$)` (blocks.py:28) lit `\s` : FF, VT, NBSP, U+2003, \x1c-\x1f, \x85, U+2028, et un `\r` qui pandoc supprime (`#\rh` est du texte `#h`). `split_md_blocks` coupe donc la citation à une ligne paresseuse que pandoc lit comme texte. Mesuré : 48 cas dans la relecture, 10 dans la sonde de la PR 324 ; tous dans le sens inoffensif (même HTML sur la page et la copie partagée). Famille du ticket 74 (F4). À mesurer contre pandoc 3.9 avant tout changement ; si la coupure est inoffensive partout, écarter avec la preuve.

**Blocked by:** none

**Claimed by:** Suraya

**Status:** ready-for-agent

- [ ] Sonde contre pandoc 3.9 : la coupure change-t-elle le HTML ou le bouton quelque part ?
- [ ] Corrigé (test rouge d'abord) ou écarté avec la preuve
