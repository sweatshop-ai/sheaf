# 26: Après l'envoi d'un message, le fil remonte tout en haut au lieu de rester en bas

**What to build:** Dans la boîte de chat, sur un document long, dès qu'un message envoyé est parti, le fil défile jusqu'en HAUT (premier message) au lieu de rester en bas où se trouve le message qu'on vient d'envoyer. Il faut faire redescendre l'ascenseur à la main à chaque envoi. Rapporté par Thierry le 2026-11-12, sur le hub en direct (2883104 depuis 12:27, PR 240 fusionnée). Attendu : après un envoi, le fil montre le bas, avec le message envoyé visible.

**Blocked by:** 04

**Claimed by:** Hakim 2026-11-12 12:31

**Status:** done (PR 249 fusionnée par Thierry, main 633d8ea, 2026-11-12)

**Ce qui ne va pas (une lecture du code, pas une preuve) :** `fillPopover` (`page.js:2008`) lit `atEnd` dans l'ancien `.rd-scroll` (`page.js:2011`) puis remplace tout le contenu de la boîte (`pop.innerHTML = …`, `page.js:2018`) : le `.rd-scroll` neuf démarre à `scrollTop = 0` et ne redescend que si `atEnd` était vrai (`page.js:2062-2063`). `atEnd` se mesure au moment de la lecture, avec la hauteur de la zone d'alors : le champ de saisie est sous le fil (`forms.forEach(pop.appendChild)`) et prend sa hauteur sur celle du fil, de sorte qu'un long texte tapé réduit le fil et que `scrollTop + clientHeight` peut rester à plus de 4 px de `scrollHeight`. Le redessin qui suit l'envoi lit alors `atEnd = false`, et le fil neuf reste en haut. À vérifier d'abord : reproduire sur un fil long avec un texte de plusieurs lignes, lire `atEnd` juste avant le redessin, et regarder si une autre voie (`openComment`, `page.js:2133-2150`, qui descend toujours) est celle qui est prise après l'envoi.

- [x] Un fil long, un message envoyé : le dernier message est visible, le fil est en bas (test rouge avant le correctif, sur un fil assez long pour défiler) — `test_after_a_send_the_thread_shows_the_message_just_sent` (rouge sur main avant le correctif)
- [x] Même chose avec un texte tapé sur plusieurs lignes, le champ ayant grandi avant l'envoi — `test_after_a_send_of_a_text_of_several_lines_the_thread_shows_the_message_just_sent`
- [x] Une réponse qui arrive pendant que l'utilisateur est en bas : le fil reste en bas — `test_an_answer_that_arrives_while_the_thread_is_at_its_end_keeps_it_there`
- [x] Un utilisateur qui a remonté lire d'anciens messages n'est pas ramené en bas par le message de quelqu'un d'autre (sa position de lecture reste) — `test_an_answer_does_not_pull_down_a_reader_of_older_messages` et `test_a_reader_who_came_back_to_the_end_stays_there_when_the_field_grows`
- [x] CI verte sur la tête de la PR, dossier de revue Codex — tête b1e1a5d, run 43272614992, 3/3 vertes ; revues : `pr-26-reviews/codex-1.md` (repli Opus, un P2 corrigé), `standards.md`, `codex-2.md` (Codex, GO) ; fusionnée en 633d8ea
