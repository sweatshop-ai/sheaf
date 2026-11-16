# agency-tiroir's record routine does not read `- [x] Shared with the team`

**What to build:** nothing in sheaf. In `acme/agency-tiroir`, `routines/record-routine/record.py` reads a box by a fixed word list (`WORDS`, line 22, and `_BOX_RE`, line 29) and writes the comment "Shared by <member> at <time>." from `SAID` (line 24). A file whose Share line says `- [x] Shared with the team` (action-buttons 03; the hub reads it as the word Share) matches none of them, so that Share would be recorded without its comment. The one-word fix there: put `"Shared with the team"` in `WORDS` and map it to `"Share"` before `MOVES`/`SAID` are looked up. It bites only once such a file exists on a tt box; the hub never writes the label into a file that holds `- [ ] Share` (`test_the_hub_never_writes_the_new_label_into_a_file_that_holds_the_old_line`), and the sheaf hub reaches agency-tiroir through a stage, so this is a stage for Alice, not a sheaf change. Read-only check of agency-tiroir at 93aa1e2, 2026-11-14: the other readers (`routines/mistral-digest/digest.py`, `ci/plan-privacy-probe.py`) write `- [ ] Share` and tick with the word `Share`, and are unaffected.

**Blocked by:** None.

**Status:** done

- [x] The record routine's `WORDS` and `_BOX_RE` take `Shared with the team` as Share, with a test, shipped to the boxes as a stage. Evidence: `acme/agency-tiroir` PR #962 merged as 3051bcd2 (main CI rerun run 43631669057 passed 2026-11-14 23:51Z); stage `record-share-label-2026-11-14` applied on agency-tiroir 2026-11-14T23:53:26Z (`apply finished`), its verify passed; the live `record.py` sha256 is now 8bd768446a7000d5ccfb559c66d34b52f87b6bcfc820503d2579426c4125e7df
