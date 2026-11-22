# 125: Restes c de la PR 352 (ticket 118) : `rd-toast` reste dans le stockage après un rechargement qui n'a pas eu lieu

**What to build:** Revue Opus de la PR 352 (`/home/tiroir/.claude/pm/chat-box-handoffs/pr-118-reviews/opus-round1.md`), constat c3, hors du diff.

- `page.js` ~1211 écrit `rd-toast` avant `reloadWhenFree`, qui peut rendre la main sans rien écrire d'autre : au `docGone` (~925) ; quand un formulaire tient le rechargement et que la personne part sur un autre document ; et `failed()` (~4517) retire `rd-keep` mais laisse `rd-toast`. Le montage suivant dans l'onglet (ou dans sa copie, « Dupliquer l'onglet » copie le sessionStorage) dit alors ce texte, sans keep pour dire à quel document il appartient (SPEC 10.11, #118).
- À décider : un `removeItem` de `rd-toast` dans `failed()` et au `docGone`, ou un document dans la valeur de `rd-toast` (changement de format, lu par les pages d'avant), ou rien. Un test rouge dans les deux premiers cas.

**Blocked by:** (none, PR 352 merged)


**Claimed by:** Britt 2026-11-14 23:49

**Status:** done (merge bf55b05, PR 364)

**Par où commencer :** `src/sheafmd/page/page.js` autour de 925, 1211 et 4517 ; tests dans `tests/page/test_page_actions.py` ; sur le serveur auto-hébergé, jamais sur le portable.

- [x] Un `rd-toast` laissé par un rechargement qui n'a pas eu lieu n'est pas dit par un autre document, ou le SPEC dit pourquoi on le laisse
