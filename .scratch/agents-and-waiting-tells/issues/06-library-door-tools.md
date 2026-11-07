# 06: Sheaf's tools in the tiroir library door

**What to build:** Thierry and Hans use sheaf from ChatGPT and Claude.ai through the tiroir library door they already have on tiroir-tt (OAuth, one door per member), with no new connector (design decisions 1, 2, 3, 9, 10). Work in `thinkingtoo/tiroir-library-mcp`, not in sheaf.

**Blocked by:** 02 (Agent tokens signed `Client (Member)`), 04 (A Tell to an agent waits on the document)

**Claimed by:** Manon 2026-11-07 07:17

**Status:** in-progress

- [x] The door offers `documents`, `threads`, `read` (read-only, marked so), `reply` and `resolve`; not `create` or `update`
  - Evidence: thinkingtoo/tiroir-library-mcp#234 (draft), `tests/test_sheaf_door.py::test_the_door_offers_the_five_tools_and_not_create_or_update` and `::test_the_three_that_read_say_so_and_the_two_that_write_do_not`. Named `sheaf_documents`, `sheaf_threads`, `sheaf_read`, `sheaf_reply`, `sheaf_resolve` because the Library already has `read` (Runa, 2026-11-07).
- [ ] It calls the hub on loopback with the token of the agent that called, chosen from the caller's MCP `clientInfo`; an unknown client or none uses the member's `AI` token; the client names each app really sends are recorded from observed `initialize` calls
  - Done in #234: token chosen by `clientInfo` (`test_the_clients_name_picks_the_token_of_that_client`, `test_an_unknown_client_or_none_uses_the_AI_token`, and on a real hub `test_a_reply_is_signed_with_the_client_and_the_member`); the map ships empty and every call logs the name. Left, Thierry's: the real names need the deploy and one call per app.
- [ ] Links in results are the page's `/list/...` address on the front, which opens it inside Open WebUI
  - Address proven on a real hub (`test_documents_through_the_real_hub_lists_the_members_own_page`). Left, Thierry's: opening it in Open WebUI, and what a signed-out person sees, need the deploy.
- [x] Waiting Tells reach the agent through `documents`
  - Evidence: `tests/test_sheaf_door_hub.py::test_a_waiting_tell_reaches_the_agent_through_documents_and_only_that_agent` against a real hub (sheaf t04 @ e515777, port 32797, pid 3400055), and the fake-hub twin.
- [x] Tests at three seams: a door call through the hub with the member's agent token; the signature per client; another member's document is refused as not existing
  - Evidence: `tests/test_sheaf_door_hub.py`, 19 tests on a real hub subprocess, run locally with `SHEAF_HUB_PYTHON` (skip without it, as on CI): seam (a) `test_threads_and_read_through_the_real_hub`, (b) `test_a_reply_is_signed_with_the_client_and_the_member`, (c) `test_another_members_document_is_refused_as_one_that_does_not_exist`.
- [ ] One agent token per client per member is made on tiroir-tt and named in that member's `tokens`, for Thierry and Hans
  - Thierry's: tokens on tiroir-tt, and whether they are made with `--write` (`sheaf_read` needs it).
