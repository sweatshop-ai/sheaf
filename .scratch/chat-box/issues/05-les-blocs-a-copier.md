# 05: Les blocs à copier

**What to build:** Quand un agent prépare un mail, un titre, une instruction ou un prompt, il l'écrit dans un bloc citation marqué `> [!COPY]`. La page l'affiche comme une citation, toujours modifiable, avec un bouton Copier. Le marquage reste lisible dans n'importe quel éditeur Markdown. Le skill `render-doc` dit aux agents de s'en servir.

**Blocked by:** 04

**Claimed by:** Torsten 2026-11-11 00:01

**Status:** in-progress

- [ ] Le bouton Copier copie le texte du bloc tel qu'il est à l'écran, modifications comprises
- [ ] Le bloc se modifie en mode Edit et se commente en mode Comment comme une citation
- [ ] La copie partagée sans script et le PDF montrent une citation normale, sans bouton
- [ ] Le skill `render-doc` et la spec décrivent le marquage
- [ ] PR séparée, CI verte
