# tt-tiroir's record routine does not read `- [x] Shared with the team`

**What to build:** nothing in sheaf. In `thinkingtoo/tt-tiroir`, `routines/record-routine/record.py` reads a box by a fixed word list (`WORDS`, line 22, and `_BOX_RE`, line 29) and writes the comment "Shared by <member> at <time>." from `SAID` (line 24). A file whose Share line says `- [x] Shared with the team` (action-buttons 03; the hub reads it as the word Share) matches none of them, so that Share would be recorded without its comment. The one-word fix there: put `"Shared with the team"` in `WORDS` and map it to `"Share"` before `MOVES`/`SAID` are looked up. It bites only once such a file exists on a tt box; the hub never writes the label into a file that holds `- [ ] Share` (`test_the_hub_never_writes_the_new_label_into_a_file_that_holds_the_old_line`), and the sheaf hub reaches tt-tiroir through a stage, so this is a stage for Thierry, not a sheaf change. Read-only check of tt-tiroir at 93aa1e2, 2026-11-14: the other readers (`routines/mistral-digest/digest.py`, `ci/plan-privacy-probe.py`) write `- [ ] Share` and tick with the word `Share`, and are unaffected.

**Blocked by:** None.

**Status:** open

- [ ] The record routine's `WORDS` and `_BOX_RE` take `Shared with the team` as Share, with a test, shipped to the boxes as a stage
