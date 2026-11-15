# 05: Where the original of a page lives: the laptop or the tiroir

**Type:** grilling
**Status:** resolved (2026-11-15)
**Blocked by:** 01, 02
**Map:** ../map.md

## Question

Today the `.md` on the laptop, in its git repo, is the source of truth and the page is a view of it. With the page on a tiroir: does the laptop file stay the original, with the tiroir holding a copy whose edits and comments come back; or does the original move to the tiroir, with the laptop's agents reading and writing it there? What does each choice do to documents that live inside a code repo (plans, specs, handoffs), to conflicts between an agent's write and a person's save, and to the rule that a document Thierry is editing is never overwritten?

## Answer

Resolved 2026-11-15 by Ottilie grilling with Thierry (one round, plus one question Thierry raised).

1. **Two kinds of page, two answers.** A page inside a git repo with a remote (plans, specs, handoffs, `~/.claude`) and a **loose page** (a session scratchpad, `/tmp`, no repo) keep their original in different places.
2. **A loose page's original moves to the tiroir.** The agent makes and changes it through the door (`create`/`update`, a stale write refused). The laptop keeps no copy, or a throwaway one.
3. **A repo page's original is git, not a machine.** The tiroir holds a clone of the repo; every save on the page is a commit and a push, and the laptop pulls. The clone works on the repo's working branch (`dev` where one exists), never on a branch that deploys. Other agents keep reading the repo as today. Rejected: a branch of its own for pages, merged by the agent; and the original moving to the tiroir with the repo file updated only when the agent takes it back.
4. **"Never overwrite" becomes mechanical.** No agent writes a page without having read its latest version (the door's hash, or a pull before editing). On a conflict both texts stay; the agent never picks its own.
5. **Chat clients are in, through the same door** (raised by Thierry). Claude.ai, ChatGPT and the assistant inside Open WebUI have no laptop file, so every page they make is a loose page. The member's tiroir library door (OAuth, SPEC 9.7) is the one write path for every agent that does not go through git: laptop sessions and chat clients alike. That door has only five read/reply tools today (ticket 02); `create`/`update` there serves both at once. A chat client's `update` on a repo page writes the file in the tiroir's clone, and the hub commits and pushes it like a save from the page.

The map's Destination was widened to include chat clients. New term in `GLOSSARY.md`: **Loose page**.
