# 41: Le nom de l'agent dans les événements d'un Tell ne concorde pas avec `tell-queued` après un renommage, ni pour une ligne écrite avant le ticket 23

**What to build:** Après le ticket 23, `tell-seen`, `tell-done` et `tell-cancelled` nomment l'agent par `waiting._name(t)` : le nom signé courant du jeton s'il existe encore, sinon le nom gardé dans la ligne (`agent`, écrit à la mise en attente). Deux écarts, trouvés par la revue Opus du tour 1 (`pr-23-reviews/opus-round1.md`, c2 et c3). (1) Une ligne de `tells.json` écrite avant le ticket 23 n'a pas `agent` : si son jeton est révoqué, l'événement nomme le jeton (`ada-chatgpt`) alors que la page tient `ChatGPT (Ada)`, et la ligne reste jusqu'au prochain instantané. (2) Après le renommage d'une personne ou d'un membre, ou un jeton passé à un autre membre, le nom courant ne concorde plus avec celui de `tell-queued` que la page a gardé ; sur la socket proxy un membre peut entendre le nom d'un autre membre dans trois événements de plus (c'était déjà vrai de l'instantané `telling`). Classe : c.

**Blocked by:**
- External: the PR of chat-box/23 (ticket 23) merged into main (same waiting.py)

**Établi (preuves) :** lecture de `waiting.py` `_name`, `queue`, `_end`, `take` à la tête bbf4dbe de chat-box/23. Non reproduit.

**Par où commencer :** décider quel nom fait foi (celui de la mise en attente, gardé dans la ligne, partout : événements et `waits()`), et le dire dans la SPEC 9.8 ; pour les anciennes lignes, un repli sur le nom courant du jeton ou, à défaut, le nom du jeton comme aujourd'hui.

- [ ] Un test : une ligne sans `agent` dont le jeton est révoqué, et un renommage entre `tell-queued` et `tell-seen` ; l'événement nomme l'agent comme `tell-queued`
- [ ] La SPEC 9.8 dit quel nom fait foi
