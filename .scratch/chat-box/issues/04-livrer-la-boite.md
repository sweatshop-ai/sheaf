# 04: Livrer la boîte : review, CI, fusion

**What to build:** La boîte de chat arrive sur `main` de `sweatshop-ai/sheaf` : une PR de la branche `cleo/chat-box`, relue, avec la suite complète verte en CI.

**Blocked by:** 01, 02, 03

**Claimed by:** Birgit 2026-11-10 10:33

**Status:** in-progress

- [x] Review standards et spec, puis bug hunt Codex, chaque point traité ou écarté avec sa raison
  - Preuve : https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6764090310 (standards + spec) et https://github.com/sweatshop-ai/sheaf/pull/238#issuecomment-6764275104 (bug hunt Opus, un P1 corrigé). Codex n'a pas pu tourner (plus de jetons jusqu'au 2026-11-11 08:36) : son passage reste à faire, ses points deviendront des tickets.
- [x] Suite complète verte en CI sur le dernier commit de la PR
  - Preuve : run 42835194794 sur 54abdda, deux passages verts de suite (ubuntu-24.04 py3.13, total_count 1, 962 passed, 1 xfailed la première fois et la seconde). À refaire si la tête de la PR change.
- [x] Mêmes garanties dans la page autonome et dans la page montée
  - Preuve : la page montée a des tests pour la sélection qui ouvre la boîte, le mode édition, Ctrl+C, le bouton refusé, le clic après un glissement, et le relâchement tactile (tests/page/test_mount_touch.py). Écarts nommés (surbrillance, Close/Resolve, liste des non-envoyés, attente au rechargement, Shift+Enter, pointerup/click comme relâchement, tape sur zone vide) : voir le premier commentaire de la PR.
- [ ] Fusionnée, branche supprimée, statut des tickets mis à jour avec le sha de fusion
- [ ] Le track action-list (Rocco) est prévenu : l'arrivée sur tiroir-tt passe par sa montée de version du hub
