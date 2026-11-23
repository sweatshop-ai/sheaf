# Handoff: ticks for tickets 181 D, 179, 96 and Ciro's worktree cleanup

**State:** done, all on main. Nothing open in this session.

## Done
- **Ticket 181 box D** ticked with the merge of #601, d497aacc (a67e810f). Branch `gilles/181-D-stale-join` and its worktree removed, local and remote.
- **Ticket 179 boxes 17, 18, 19** ticked (0c09dcc6). #586 merged in c67d3853 with no occurrence of the CI runner host's name under `.scratch/`; #587 merged in 730a94f5 with none outside it, the guard regex no longer naming it. Four occurrences written later (tickets 137 and 180, the 137 test-hygiene handoff; from 1d00407d and 9b2effe6) replaced in 24ceac2e. `git grep -i -E` of the hyphen, underscore, space and joined spellings over the tree then finds only `getComputedStyle` and "it computes".
- **Ticket 96 box "SPEC examples carry a real first name and a personal host name"** ticked (96235465): cleaned by 6580535f (2026-11-16) before ticket 155 closed. The three examples now use `alice`, `agency-tiroir`, `alice-laptop`; no first name of the owner or the team is left in `SPEC.md`. No PR needed.
- **Ciro's worktrees** `sheaf-wt-ciro-178`, `-179`, `-179b` and branches `ciro/178-selftest-fails-closed`, `ciro/179-scratch-host`, `ciro/179-tests-spec-host` removed, local and remote. Each checked first: 0 commits not on origin/main, no live session named Ciro, no process with its cwd there, no uncommitted change.

## Next
1. Ticket 179 box 20 is the owner's: add the term to `SHEAF_PUBLIC_TREE_TERMS` with a leading `=`. Until then nothing in CI keeps the name out, and sessions keep writing it in `.scratch/` notes (four in one day).
2. Codex recheck of #601's provisional round if the track asks for one.
