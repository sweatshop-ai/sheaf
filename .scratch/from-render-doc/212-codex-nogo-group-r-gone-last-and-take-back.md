# 212: gone is not the last event for a stale entry; the take-back can still lose an editor's write

**Claimed by:** Anouk

**Status:** in progress (2026-11-26)

**Blocked by:** none

**From:** Codex re-check of PR #688, round 3 (NO-GO), group R of the boss's seventh pass.

**Where:** `src/sheafmd/hub/live.py` (`_tell_grants` and other hub paths publishing on an `Entry`), `src/sheafmd/mcp.py` (take-back of a refused create).

## Serious

- [ ] **A.** The forgotten gate covers only `LiveDocument` publications. `_tell_grants` holds a stale `Entry` and calls `e.bus.publish(...)` directly; a delete can publish `gone` before that publish, so `gone` is not the stream's last event. Red test first.
- [ ] **B.** The take-back checks the file with `fstat`, then unlinks it. An editor holding an open descriptor can write between the two (and a same-size write can pass a coarse mtime), and the unlink deletes that write. The take-back must not be able to delete data: keep the file aside rather than delete it when a late write cannot be ruled out. Red test first.
- [ ] **C.** The directory fallback uses a plain `rename`, which on POSIX replaces an empty directory that arrived at the path. Nothing may be replaced: `renameat2(RENAME_NOREPLACE)` or an equivalent. Red test first.
