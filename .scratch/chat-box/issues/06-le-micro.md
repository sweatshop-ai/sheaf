# 06: Le micro dans la boîte

**What to build:** Un bouton micro dans la boîte de chat permet de dicter dans le champ, comme dans le chat de tiroir. La voix est transcrite par notre service, pas par la reconnaissance vocale de Google. Dans tiroir, la dictée s'appuie sur la transcription qu'Open WebUI expose déjà.

**Blocked by:**
- 04
- External: Rocco lit la config de transcription de tiroir-tt après P7, puis Thierry choisit la source

**Status:** ready-for-agent

- [x] Vérifié ce que tiroir-tt a d'activé pour la transcription ; **version d'Open WebUI : pas relevée**, et aucun aller-retour de dictée réel (il faut le jeton d'une personne connectée). Preuve : lecture seule du track de Rocco, 2026-11-12 10:18-10:20Z, `/home/tiroir/.claude/pm/action-list-p7/stt-read.md` : moteur vide = faster-whisper local, modèle `base`, aucune clé STT, modèle présent sur disque, extensions `mp3 wav m4a webm ogg flac mp4 mpga mpeg`.
- [x] Décision de Thierry (2026-11-12, q22) : sur une page servie par le hub du laptop, sans Open WebUI, la dictée est transcrite par le service de transcription de t-compute, par Tailscale ; t-compute injoignable = pas de bouton micro.
- [ ] Dans tiroir, dicter remplit le champ et le texte reste modifiable avant l'envoi
- [ ] La politique de sécurité de la page montée laisse passer le micro
- [ ] Sans transcription disponible, pas de bouton micro mort

**Plan :** `.scratch/chat-box/plan-06-micro.md` (branche `chat-box/06`). Aucun code avant sa relecture. Questions ouvertes du plan : A (hub en mode proxy, page non montée), B (authentification et disponibilité côté Open WebUI), C (clé de t-compute dédiée à sheaf), D (langue de la dictée).
