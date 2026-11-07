# 01: Retire Ask end to end

**What to build:** Ask disappears from sheaf everywhere a person or an agent could meet it, as SPEC 11.2 and D25 describe. The page offers Tell only; the hub no longer runs a fork of a session; replies Ask left in files keep their role `answer` and still show as "<name>'s answer". Design 2026-11-07, decision 8.

**Blocked by:** None (can start immediately)

**Claimed by:** Anders 2026-11-07 01:42

**Status:** done

- [x] The page has no Ask button, no "Send and ask", no "is answering" line, and its Agent menu line reads "Tell → …" (evidence: tests/page/test_page_agent.py:52,66,73 (no button.rd-ask); test_page_assets.py::test_the_page_has_no_ask_left; head 628d9a7, CI run 42327063265 success)
- [x] `/_/ask` is gone; a comment add or reply carrying `ask` is refused 400 "Ask was retired: use Tell, or reply." and writes nothing (evidence: handler.py:1499 (ASK_RETIRED, 400 before any write); handler tests post ask and compare file bytes; head 628d9a7, CI run 42327063265 success)
- [x] No `asking` in `/_/doc`, `/_/jobs`, `changed` or anywhere else; no `ask-*` event is ever sent (evidence: no ask/asking/ask-* in src (grep, Opus bug hunt on 628d9a7); head 628d9a7, CI run 42327063265 success)
- [x] The adapter interface has no `ask_command` and no `ask` capability; the Claude Code adapter's capabilities are deliver, state, stop (evidence: agents/base.py, claude_code.py, generic.py CAPS; tests/test_agents_adapters.py; head 628d9a7, CI run 42327063265 success)
- [x] Box drops (SPEC 9.12) always carry `kind: "tell"`; `sheaf deliver` refuses a drop of `kind` `ask` with exit 2 and delivers nothing (evidence: handler.py:1277 kind tell; deliver.py:141 exit 2; deliver tests with and without message; head 628d9a7, CI run 42327063265 success)
- [x] `/_/cancel` takes `{doc, id}` and ignores a `what` other than `tell` (evidence: test_hub_handler.py:596 test_cancel_ignores_a_what_it_is_given (ask, tell, both); head 628d9a7, CI run 42327063265 success)
- [x] An existing `answer` reply (rd-comment and sheaf-comment fixtures) renders and parses as before; no file is rewritten (evidence: tests/test_answer_replies_survive.py, test_markers_roles.py; nothing rewrites a file; head 628d9a7, CI run 42327063265 success)
- [x] The module that held Ask and Tell is renamed for Tell alone, as the SPEC package layout names it (evidence: hub/asktell.py -> hub/tell.py; tests/test_hub_tell.py; head 628d9a7, CI run 42327063265 success)
- [x] Tests: the handler refuses `ask`; the page shows no Ask control (Playwright); the deliver refusal; no test still drives an Ask (evidence: handler refusal tests; tests/page/test_page_agent.py:52; deliver refusal tests; no Ask-driving test left; head 628d9a7, CI run 42327063265 success)
