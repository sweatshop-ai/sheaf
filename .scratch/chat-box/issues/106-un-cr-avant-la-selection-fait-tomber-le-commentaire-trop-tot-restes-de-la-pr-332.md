# 106: Un CR avant la sélection : le commentaire tombe un caractère trop tôt par CR (restes de la PR 332)

**What to build:** Reste c de la relecture étroite de la PR 332 (tickets 103 et 95), `/home/tiroir/.claude/pm/chat-box-handoffs/pr-103-reviews/opus-2-narrow.md`. Quand un CR précède la sélection dans le bloc, `comments.py` (`anchor_point` / projection, vers la ligne 594) place le commentaire un caractère trop tôt par CR : `para\r Title` donne `Titl<!--…-->e`, `\r> quote Title` pareil. Déjà vrai sur main. La PR 332 le rend atteignable dans plus de documents : quatre CR ou plus avant un bloc faisaient du code indenté (commentaire refusé), ce sont maintenant un paragraphe, une citation ou une liste, et le commentaire est ajouté, 4 caractères trop tôt. Entrée : `\r\r\r\r> quote Title\n`, commentaire sur « Title » → `\r\r\r\r> quote T<!-- sheaf-comment … -->itle`. La page est identique (le mot reste entier à l'écran) ; seul le texte brut est abîmé. À mesurer contre pandoc 3.9 avant le correctif ; test rouge d'abord.

**Autre reste (même relecture) :** `edit.TASK_MARK_RE` (l. 718, usages 754 et 782) ne reconnaît pas une liste devenue liste par ses 4 CR de tête (`\r\r\r\r- [ ] x`) : cocher la case passe par la sauvegarde pandoc normale au lieu de basculer une marque. Rien n'est perdu ; à écarter avec la preuve ou à aligner.

**Blocked by:** none

**Claimed by:** (libre)

**Status:** ready-for-agent

- [ ] Le commentaire tombe après la sélection quand des CR la précèdent, mesuré contre pandoc 3.9
- [ ] `TASK_MARK_RE` : corrigé ou écarté avec la preuve
