# 01: Retire Ask end to end

**What to build:** Ask disappears from sheaf everywhere a person or an agent could meet it, as SPEC 11.2 and D25 describe. The page offers Tell only; the hub no longer runs a fork of a session; replies Ask left in files keep their role `answer` and still show as "<name>'s answer". Design 2026-11-07, decision 8.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The page has no Ask button, no "Send and ask", no "is answering" line, and its Agent menu line reads "Tell → …"
- [ ] `/_/ask` is gone; a comment add or reply carrying `ask` is refused 400 "Ask was retired: use Tell, or reply." and writes nothing
- [ ] No `asking` in `/_/doc`, `/_/jobs`, `changed` or anywhere else; no `ask-*` event is ever sent
- [ ] The adapter interface has no `ask_command` and no `ask` capability; the Claude Code adapter's capabilities are deliver, state, stop
- [ ] Box drops (SPEC 9.12) always carry `kind: "tell"`; `sheaf deliver` refuses a drop of `kind` `ask` with exit 2 and delivers nothing
- [ ] `/_/cancel` takes `{doc, id}` and ignores a `what` other than `tell`
- [ ] An existing `answer` reply (rd-comment and sheaf-comment fixtures) renders and parses as before; no file is rewritten
- [ ] The module that held Ask and Tell is renamed for Tell alone, as the SPEC package layout names it
- [ ] Tests: the handler refuses `ask`; the page shows no Ask control (Playwright); the deliver refusal; no test still drives an Ask
