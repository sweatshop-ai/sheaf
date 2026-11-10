# 06: Le micro dans la boîte

**What to build:** Un bouton micro dans la boîte de chat permet de dicter dans le champ, comme dans le chat de tiroir. La voix est transcrite par notre service, pas par la reconnaissance vocale de Google. Dans tiroir, la dictée s'appuie sur la transcription qu'Open WebUI expose déjà.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Vérifié ce que tiroir-tt a d'activé pour la transcription, et sa version d'Open WebUI
- [ ] Décision de Thierry : d'où vient la transcription sur un hub local, sans Open WebUI
- [ ] Dans tiroir, dicter remplit le champ et le texte reste modifiable avant l'envoi
- [ ] La politique de sécurité de la page montée laisse passer le micro
- [ ] Sans transcription disponible, pas de bouton micro mort
