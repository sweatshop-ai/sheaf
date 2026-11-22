# 179: The CI runner host's name leaves the public tree

**Claimed by:** Ciro

**Status:** in-progress: boxes 1 to 3 in PRs #586 and #587, not merged yet; box 4 is the owner's

**From:** ticket 99 line 52 and the three Codex rounds of PR #580 (closed unmerged), 2026-11-22

**Where:** 57 tracked files under `.scratch/` (38 in `chat-box/`, 11 in `from-render-doc/`, 8 in `follow-ups/`); 5 comments or docstrings in `tests/page/` (`pagehelp.py`, `test_mount_allowlist.py`, `test_mount_selection.py`, `test_mount_sheaf.py`, `test_page_dictation.py`); 3 sentences of `SPEC.md` (the `[transcribe]` paragraph and the key paragraph of 8.5); the guard regex of `tests/test_ci_workflow.py` (`test_an_ubuntu_job_of_this_repository_runs_on_…`); the `SHEAF_PUBLIC_TREE_TERMS` secret, which does not hold the name.

The organisation's CI runner host is named in the public tree. `tests/public_tree.py` scans every tracked file for the terms of the secret, but the secret lacks this one, and it cannot take it while any tracked file still names the host, or CI turns red. Do not write the name in this ticket, a PR, a commit message or a comment: say "the CI runner host". Find it with the term the owner gives, or from the guard regex.

In this order:

- [ ] `.scratch/`: replace the name in the 57 files (58 by 2026-11-22: 12 in `from-render-doc/`; PR #586, 4 commits, Codex GO round 2 on 6e7c21ca) with "the CI runner host" (or "a self-hosted server" where it is the speech-to-text server). Other sessions edit these files: one commit per folder, staged by path, `git status` first.
- [ ] The 5 test comments and 3 SPEC sentences, as in PR #580 at 1d00d833 (same wording). PR #587; the test comments say "the organisation's runners" after review. Not in the list above, also in #587: `tests/test_hub_transcribe.py` spelled the name without its hyphen as the fake provider class and its fixture (117 lines), now `FakeProvider` and `provider`; and the SPEC key sentence named a person, now "the owner's hub". The count of 26 occurrences in 10 files given on 2026-11-22 was wrong: that search also matched `getComputedStyle`.
- [ ] `tests/test_ci_workflow.py`: drop the name from the guard regex, with a comment that the public-tree guard covers it. Never a hash: `tests/public_tree.py` forbids hashes of names. Acceptance: `git grep -i` of the name finds nothing in the tree. PR #587 (Opus fallback GO rounds 1 and 2, Codex at its usage limit); outside `.scratch/` only `getComputedStyle` is left.
- [ ] The owner adds the term to `SHEAF_PUBLIC_TREE_TERMS` (only the owner can). Acceptance: the next CI run of `test_public_tree.py` passes with the term in the secret. **Enter it with a leading `=`** (whole words only): `tests/public_tree.py` finds a plain term inside longer words, and a plain entry hits `getComputedStyle` and "it computes" 26 times outside `.scratch/` and turns CI red; with `=` it finds none there (both run locally on the #587 branch, 2026-11-22). The `=` form still catches the hyphen, underscore and joined spellings, not one inside a CamelCase word. Until the term is in, nothing in CI keeps the name out of `ci.yml`: the old regex was that guard. Add it soon after #586 and #587 merge.

**Recorded (low risk):** a commit on the closed branch of PR #580, dropped by a force-push, held a SHA-256 digest of the name in `tests/test_ci_workflow.py`. GitHub still serves that commit by its sha. The digest is of a name the history already holds in clear text, so it publishes nothing new; it is recorded, not acted on. The history itself is not rewritten by this ticket.
