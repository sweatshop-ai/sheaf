# 06: Le micro dans la boîte

**What to build:** Un bouton micro dans la boîte de chat permet de dicter dans le champ, comme dans le chat de tiroir. La voix est transcrite par notre service, pas par la reconnaissance vocale de Google. Dans tiroir, la dictée s'appuie sur la transcription qu'Open WebUI expose déjà.

**Blocked by:**
- 04
- External: Rocco lit la config de transcription de tiroir-tt après P7, puis Thierry choisit la source

**Status:** ready-for-agent

**Fait :** PR 270 (partie page, 2 sur 3) fusionnée dans main (cd3e0da, 2026-11-13). Reste la troisième partie, la clé de dictée dédiée sur t-compute (externe). Le ticket reste ouvert.

**Fait :** PR 284 fusionnée (c3a6ddf) : la dictée parle l'API standard ; reste le côté t-compute (route /v1/audio/transcriptions) et le déploiement par Thierry

- [ ] Vérifié ce que tiroir-tt a d'activé pour la transcription, et sa version d'Open WebUI
- [ ] Décision de Thierry : d'où vient la transcription sur un hub local, sans Open WebUI
- [ ] Dans tiroir, dicter remplit le champ et le texte reste modifiable avant l'envoi
- [ ] La politique de sécurité de la page montée laisse passer le micro
- [ ] Sans transcription disponible, pas de bouton micro mort
