# 04: Merge, Deploy and Install are action words

**What to build:** `Merge`, `Deploy` and `Install` join the fixed list of one-off action words (9.10). Their argument is the rest of the line (`Merge sweatshop-ai/sheaf#272: …`), which the hub does not read; AgentView's merge desk does. The list stays fixed: no author can make a new word.

**Blocked by:** None (can start immediately).

**Claimed by:** Karim 2026-11-13 22:47

**Status:** done

- [x] `- [ ] Merge owner/repo#N: text` is a one-off action; pressing it writes `[x]` and nothing else
  Evidence: tests/test_hub_list.py::test_merge_deploy_and_install_are_actions_that_take_the_rest_of_the_line and test_a_pressed_merge_writes_only_its_tick_… (press writes `[x]`, file equals the original with that one mark flipped): 7 passed
- [x] A save that unticks a pressed Merge is refused as for the other one-offs, but a write by another process (AgentView unticking a refused merge) is taken as an outside change
  Evidence: same test: POST /_/tick release on a pressed Merge → 409 "Merge is pressed once…", file unchanged; a direct file write unticking it (AgentView) is read by the list as a Merge button again; whole tests/test_hub_list.py 187 passed
- [x] SPEC 9.10's table lists the three words
  Evidence: SPEC.md 9.10 'What a sheaf says' lists eleven words incl. Merge/Deploy/Install, rule for the rest of the line; GLOSSARY updated
