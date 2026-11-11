# 01: The attach command never names a window two projects share

**What to build:** `work_meta` builds the tmux window name for the "attach to James's window" command by joining the sheaf's `<client>/<project>` with `_`. A name with `_` in a component is not told apart: `a_b/c` and `a/b_c` both give `a_b_c`, so one project's page offers the attach command of the other's window. Found by the Codex post-merge pass on sheaf PR 20 (merge ae689273), P2, confirmed on main cdb0e24 (`src/sheafmd/hub/core.py:724-728`, same two lines as at the merge). Reported in thinkingtoo/tt-tiroir#59, comment 6794176457.

**Where (main cdb0e24):** `hub/core.py:724-728` `work_meta`: `window = "_".join(...rel.split("/")[:2])`, then `re.fullmatch(r"[A-Za-z0-9_-]+", window)` lets `_` through. The join follows James's own naming (`<client>_<project>`, the comment on line 724), so changing the separator needs James's naming to change with it; refusing the ambiguous name does not.

**The decision to make first:** (a) refuse the `attach` command when either component holds a `_`, so the page offers none rather than a wrong one; or (b) a reversible name shared with James's window naming. (a) is the smaller change and needs nothing from James; (b) keeps the command for such projects and needs James's side changed in step. Pick one with Thierry before building; write the choice into SPEC 9.12 either way.

**Blocked by:** the decision above.

**Claimed by:** nobody

**Status:** ready-for-human

- [ ] `a_b/c` and `a/b_c` never produce the same `attach` command (evidence: a test with both addresses, asserting they do not share one command)
- [ ] A project with no `_` in either component keeps the command it has today (evidence: the existing attach tests in tests/test_hub_work.py stay green and unchanged)
- [ ] SPEC 9.12 states the rule and why (evidence: the sentence, with the section number)
