# 179: The CI runner host's name leaves the public tree

**Claimed by:**

**Status:** open

**From:** ticket 99 line 52 and the three Codex rounds of PR #580 (closed unmerged), 2026-11-22

**Where:** 57 tracked files under `.scratch/` (38 in `chat-box/`, 11 in `from-render-doc/`, 8 in `follow-ups/`); 5 comments or docstrings in `tests/page/` (`pagehelp.py`, `test_mount_allowlist.py`, `test_mount_selection.py`, `test_mount_sheaf.py`, `test_page_dictation.py`); 3 sentences of `SPEC.md` (the `[transcribe]` paragraph and the key paragraph of 8.5); the guard regex of `tests/test_ci_workflow.py` (`test_an_ubuntu_job_of_this_repository_runs_on_…`); the `SHEAF_PUBLIC_TREE_TERMS` secret, which does not hold the name.

The organisation's CI runner host is named in the public tree. `tests/public_tree.py` scans every tracked file for the terms of the secret, but the secret lacks this one, and it cannot take it while any tracked file still names the host, or CI turns red. Do not write the name in this ticket, a PR, a commit message or a comment: say "the CI runner host". Find it with the term the owner gives, or from the guard regex.

In this order:

- [ ] `.scratch/`: replace the name in the 57 files with "the CI runner host" (or "a self-hosted server" where it is the speech-to-text server). Other sessions edit these files: one commit per folder, staged by path, `git status` first.
- [ ] The 5 test comments and 3 SPEC sentences, as in PR #580 at 1d00d833 (same wording).
- [ ] `tests/test_ci_workflow.py`: drop the name from the guard regex, with a comment that the public-tree guard covers it. Never a hash: `tests/public_tree.py` forbids hashes of names. Acceptance: `git grep -i` of the name finds nothing in the tree.
- [ ] The owner adds the term to `SHEAF_PUBLIC_TREE_TERMS` (only the owner can). Acceptance: the next CI run of `test_public_tree.py` passes with the term in the secret.

**Recorded (low risk):** a commit on the closed branch of PR #580, dropped by a force-push, held a SHA-256 digest of the name in `tests/test_ci_workflow.py`. GitHub still serves that commit by its sha. The digest is of a name the history already holds in clear text, so it publishes nothing new; it is recorded, not acted on. The history itself is not rewritten by this ticket.
