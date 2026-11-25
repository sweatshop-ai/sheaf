# 190: Codex NO-GO findings on merged PRs #561 and #560 (security claims and design notes)

**Claimed by:** Wilma

**Status:** done in PR #655 (`wilma/190-security-claims`); one minor point left open, below

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone (round05 of each). #561 changed SPEC and README on the
peer (OS-user) check; #560 added `.scratch/follow-ups/recheck-c-sorted-2026-11-20.md`, a sorted list of findings with
recommended options. Every finding below was checked against `origin/main` at f3e370bc.

## #561: SPEC and README on the OS-user check

- [x] A [SERIOUS] SPEC 9.10 ("Two listeners") says every caller of the loopback port, the MCP door with a token included,
  is judged by the user of its connection. `Handler._gate` runs for the key and the cookie only; SPEC 9.1 already says an
  MCP token is not looked up. Holds on main. Fix: say the key and the cookie are judged, an MCP token is not.
- [x] B [SERIOUS] README "Security" says that on Linux the key and the cookie work only over a connection of the user's own
  account, naming only macOS and Windows as exceptions. A Linux hub whose start-up self-test reads a wrong owner turns the
  check off (SPEC 9.1, `peer-check-off`). Holds on main. Fix: name that case in the README.
- [x] C [MINOR] SPEC 9.6 says `peer-refused` rows held back by the one-a-minute limit "are counted". The handler keeps no
  count (`row = False`, "not written"). Holds on main. Fix: "are not written"; the handler comment that says "counted" too.
- [x] D [MINOR] (round01) SPEC 9.1 ends "wherever the hub cannot read owners (below)"; the cases are described earlier in
  the same paragraph. Holds on main. Fix: "(above)".

## #560: the recommendations in recheck-c-sorted-2026-11-20.md

- [x] E [SERIOUS] Item 286, credential file names: `peer_credential_name` maps every character outside `[A-Za-z0-9._-]`
  to `-`, so `https://a.example:8443` and `https://a.example-8443` share one file, and the token kept for one peer is sent
  to the other. The note recommended leaving it. Holds on main (`src/sheafmd/connect.py:82-86`). Fix test-first: a name
  that no two origins share.
- [x] F [SERIOUS] Item 192, `rd-edit-meta` of a page read through: the agency hub keeps the client's block verbatim
  (`readthrough.adopt`), and the agency-origin page script takes `doc`, `actions` and the rest from it, so a client hub
  can point the agency page's reads and writes at an agency address. The note's option A (filter to the keys the
  script reads) keeps exactly the forgeable keys. Holds on main. Fix test-first: the agency hub sets `doc` itself and
  drops what a read-through page has no use for, in the page's block and the mount's config.
- [x] G [SERIOUS] Item 115, recommended option A (skip `restore` when `armedFor` differs) would leave a resumed session
  unarmed: `session.start` arms only when `p.doors` is empty, and `leave()` re-arms nothing. Not implemented on main
  (`plugin/sheaf/hooks/register.ts` `session.start` is unchanged). Fix: correct the note, A withdrawn.
- [x] H [MINOR] Item 103, recommended option A keys the `ssh -G` cache on `~/.ssh/config` mtime, which misses `Include`
  files and the system config. Not implemented on main (`repos.py` `_hosts` never expires). Fix: correct the note.
- [x] I [MINOR] Item 306 cites SPEC 8.7 for the sleeping-clone rule; it is in 8.6. Fix: correct the note.

## Evidence

- E: `tests/test_peer_channel.py::test_no_two_peer_origins_share_a_credential_name` and
  `test_a_credential_file_of_the_old_port_name_is_not_read_for_the_other_peer` failed on main, pass on the branch. A file
  under the old port name is not read; the hub names it once on stderr (`test_a_credential_file_left_under_the_old_port_name_is_said_once`).
- F: `tests/test_read_through_two_hubs.py::test_the_agency_sets_what_a_client_page_acts_on_whatever_the_client_tiroir_says`
  failed on main, passes on the branch (page meta and mount config; `work` and `way_back` dropped too).
- F, from the Codex review of this PR: a non-script element with the id `rd-edit-meta` ahead of the rewritten block was read
  by `getElementById`; page.js now reads the first `script[type="application/json"]` whose id is `rd-edit-meta`. Browser test
  `tests/page/test_page_clients.py::test_an_element_that_borrows_the_meta_blocks_id_is_not_read_as_the_meta` (CI only).
- A–D: SPEC 9.1, 9.6, 9.10 and README edited; G–I: the note's items 115, 103, 192, 286 and 306 corrected.

## Left open

- [ ] [MINOR] A host of many non-ASCII characters can give a credential name over 255 bytes (each byte escaped as three
  characters); writing it fails with OSError and reading finds nothing. No such peer exists; left until one does.
