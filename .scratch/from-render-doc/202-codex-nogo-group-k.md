# 202: Codex NO-GO findings on merged PR #655 (group K)

**Claimed by:** Boris

**Status:** in progress

**Blocked by:** none

**From:** the Codex re-check of #655 (ticket 190 fix), round 07, NO-GO. Both findings checked against main 8a909c1b: both still hold. Boxes are lettered A and B within this ticket ("202 A").

**Where:** `src/sheafmd/hub/readthrough.py` (`agency_config`, `agency_meta`), `src/sheafmd/hub/handler.py` (`_relayed`, `_agency_mount`), `src/sheafmd/connect.py` (`peer_credential_name`).

## Serious

- [ ] **A** (from #655, `hub/readthrough.py` `agency_config`): the meta block and mount config of a page read through keep the client's own `proxy` and `member`. The page script namespaces unsent comment and edit drafts in this origin's local storage by them (`DRAFTS_OF` in `page.js`), so a client tiroir that sends `proxy: false` or one fixed `member` makes two agency members in one browser profile share, overwrite or delete each other's drafts. Fix: this hub sets both, `proxy: true` and the signed-in agency member's id.
- [ ] **B** (from #655, `connect.py` `peer_credential_name`): each byte of a non-ASCII host character is written as three characters, so a valid IDN host can give a name past the 255-byte limit of a file name (50 × `é` in one label: 311 characters), and `sheaf peer use --store file` cannot keep that peer's token. Fix: a name that would pass the limit is cut and ends in a hash of the whole origin, under a marker no shorter name can carry.
