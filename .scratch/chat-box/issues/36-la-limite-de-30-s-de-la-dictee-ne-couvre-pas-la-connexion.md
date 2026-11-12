# 36: La limite de 30 s du relais de dictée ne couvre ni la résolution du nom ni l'établissement de la connexion

**What to build:** Dans `src/sheafmd/hub/transcribe.py`, `_call` coupe la socket par un `threading.Timer` à la fin de `timeout`, mais la socket n'est connue (`held`) qu'après le retour de `conn.connect()`. Une résolution DNS lente, une poignée de main TLS lente ou plusieurs adresses injoignables peuvent dépasser `timeout` : l'appelant reste bloqué, avec la clé et le corps, et le verrou `_busy` du relais tenu. Classe : c (tour 3 de Codex sur la branche chat-box/06b, verdict GO ; l'hôte est celui de `[transcribe] url`, posé par l'administrateur, pas par une requête).

**Blocked by:** aucun

**Établi (preuves) :** `codex-round3.md` de pr-06b-reviews. `socket.create_connection` borne chaque adresse par `timeout`, pas la somme ; `getaddrinfo` n'a pas de limite. Non reproduit.

**Par où commencer :** résoudre l'adresse avec une limite, ou connecter dans un fil borné qui ferme la socket ; ou, plus simple, borner le nombre d'adresses essayées et documenter que seul le DNS reste sans limite.

- [ ] Un test avec un hôte qui n'accepte pas la connexion (socket d'écoute sans `accept` et file pleine, ou adresse non routable) montre `_call` rendant `(0, b"")` dans la limite, et échoue sans le correctif
- [ ] Le docstring de `_call` ne promet que ce qui est tenu
