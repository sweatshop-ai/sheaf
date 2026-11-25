# Handoff: ticket 190 done, Codex NO-GO group C (security claims) (2026-11-25)

**Status:** done. #655 merged as 6b4639c4 through the gate (round03 GO, provisional Opus fallback; the last commit, a test update, under the test-only rule; CI green on 003e4a79).

## Done

- #561 (SPEC and README on the OS-user check): A–D fixed in #655. SPEC 9.1, 9.6, 9.10 and the README "Security" section now say what the code does.
- #560 (recommendations in the recheck note):
  - E (credential file names): fixed test-first in #655. No two peer origins share a credential name; a file under the old name is not read and is named once on stderr, also for an IPv6 peer with no port.
  - F (`rd-edit-meta` of a page read through): fixed test-first in #655 and hardened over two review rounds. Every block `adopt` keeps as meta is the agency's, in an HTML answer of any status; page.js reads the meta from the JSON script of that id alone.
  - G, H, I: corrections to the note. None of those recommendations had been implemented in code.
- Ticket `.scratch/from-render-doc/190-codex-nogo-group-c-security-claims.md`: every box ticked with evidence.

## Worth knowing

- Before upgrading a service hub that reads a peer credential: a peer whose origin has a port or is IPv6 is now looked up under a new file name. Keep its token again with `sheaf peer use --store file`, and update `LoadCredential=` in the unit to the new name. The hub says the old name once on stderr.
- A client meta block that is JSON but not an object is now rebuilt by the agency (SPEC 9.9); it was passed on as it came before.
- Left open (MINOR): a host of many non-ASCII characters can give a credential name over 255 bytes. No such peer exists.
