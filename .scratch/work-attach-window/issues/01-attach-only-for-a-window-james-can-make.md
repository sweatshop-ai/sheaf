# 01: The attach command is offered only for a window James can make

**What to build:** `work_meta` builds the tmux window name for the "attach to James's window" command by joining the sheaf's `<client>/<project>` with `_` and accepting anything that matches `[A-Za-z0-9_-]+`. James is stricter: his `project_window` (tt-tiroir `routines/james/james.py:465-469`) returns `<client>_<project>` only when both parts match `SLUG = [a-z0-9][a-z0-9-]*` (`james.py:179`), and returns None otherwise, so he never makes a window for a part holding `_`, an uppercase letter or a leading `-`. Sheaf therefore offers an `attach` command for windows James cannot make, and for `a_b/c` and `a/b_c` the same command, which names one window for two projects. Found by the Codex post-merge pass on sheaf PR 20 (merge ae689273), P2, confirmed on main cdb0e24 and by the Opus review of the ticket; reported in thinkingtoo/tt-tiroir#59, comment 6794176457.

**Where (main cdb0e24):** `hub/core.py:724-728` `work_meta`: `window = "_".join(...rel.split("/")[:2])`, then `re.fullmatch(r"[A-Za-z0-9_-]+", window)`. `Address.parse` (`hub/roots.py:180-186`) restricts no segment. The fix: check each of the two parts against James's SLUG before joining; a part that fails gets no `attach` key. Nothing is lost: James has no window for such a project. Nothing changes on James's side.

**Size:** small: one check in `core.py`, tests, one sentence in SPEC 9.12.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Test first: `a_b/c` and `a/b_c` each get no `attach` key (evidence: a test with both addresses on a member with a shell and `attach` configured)
- [ ] A part with an uppercase letter or a leading `-` gets no `attach` key either (evidence: a test for `Thinkingtoo/tiroir` and `-a/b`)
- [ ] `thinkingtoo/tiroir` and a part with inner dashes (`a-b/c`) keep today's command (evidence: the attach tests at tests/test_hub_work.py:963-993 stay green and unchanged)
- [ ] SPEC 9.12 states the rule and names James's SLUG as its source (evidence: the sentence, with the section number)
