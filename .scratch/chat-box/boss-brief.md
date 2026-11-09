# Boss brief: boîte de chat des commentaires sheaf

Written 2026-11-09 by Cleo with `/hand-to-boss`. You are the boss for
track `chat-box`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full) | `/home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/plan.md` |
| Tickets, one file each, in dependency order | `/home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/issues/` |
| Handoffs | `/home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/handoff-cleo-2026-11-09.md` |
| Research | none |
| Code | `/home/tiroir/Projects/sheaf-wt/cleo-chat-box` (branch `cleo/chat-box`, remote `origin` = `sweatshop-ai/sheaf`, merges to `main`) |

## Frontier

The frontier on 2026-11-09 16:20 CET, from `frontier.py /home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/issues`:

```
Ready now: 01
  01  Le fil en boîte de chat : champ ouvert, bandeau, texte gardé
Waiting on other tickets:
  02  after 01
  03  after 02
  04  after 01, 02, 03
  05  after 04
  06  after 04
Done: none
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.22.0/skills/hand-to-boss/frontier.py /home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/issues`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| 03 | iPhone back online on Tailscale (`iphone-14-pro` was offline on 2026-11-09), then a trial by finger | Thierry | not yet; ask only once the link is proven to work |
| 06 | Where transcription comes from on a local hub without Open WebUI | Thierry | not yet; named in the plan as open |
| 04 | Merge to `main`: an earlier merge there was refused by the classifier and reported to the dispatcher (memory `classifier-block-on-merge-goes-to-farid`) | Thierry, if it recurs | not yet |

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked; the ones still
waiting are listed with who holds them. Give it a `## Tickets` section holding
`/home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/issues`, one line: the pulse then reads the frontier itself and hands you
every ready ticket each time a worker goes idle.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/sheaf-wt/`.
  Two workers never share a branch or a worktree. Workers 01 to 03 branch from
  `cleo/chat-box` and merge back into it; ticket 04 opens the PR from it to `main`;
  tickets 05 and 06 branch from `main` after that merge. Nobody edits code in `/home/tiroir/Projects/sheaf-wt/cleo-chat-box`.
- At most 3 workers at once (12 is the span of control): as many as the
  frontier has ready tickets.

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.22.0/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/sheaf-wt/cleo-chat-box/.scratch/chat-box/issues <NN> <worker>
git -C /home/tiroir/Projects/sheaf-wt/cleo-chat-box commit -m "Claim <NN> for <worker>" -- <ticket file>
```

`claim` writes `**Claimed by:** <worker> <date time>` (replacing an existing
`Claimed by` line) and
sets `**Status:** in-progress`, under a lock, in the shared ticket file. It
refuses (exit 3, naming the claimant) a ticket that is already claimed, done or
still blocked; then nothing is dispatched. A ticket may carry `**Claimed by:**`
empty or with `none`, `nobody` or `-` (any case): all mean unclaimed. The commit names that one file by
path, so it carries nothing else in a tree other sessions share, and no edit is
left uncommitted. Both are coordination, not implementation: if the guard
remarks on them, say so in one line and carry on.

The worker never edits the claim. It reads the ticket at its path under
**Sources**, the shared file, never the copy inside its own worktree, and when
it finishes it ticks the boxes and sets Status there, committing that file by
path in the same way. To release a claim, the boss removes the line, sets
Status back to `ready-for-agent`, commits the file by path and notes it in the
tracker.

## Done means verified

A worker ticks an acceptance box only when it has the evidence: the command it ran
and what came back, the URL it read, the test that passed. It puts that evidence
in its report. Status becomes `done` only when every box is ticked. A box that
cannot be verified yet stays unticked with one line saying why.

## Guardrails

Quoted from the rules that bind this work. The source is named on each line; the
source wins where this summary is short. The sheaf repo has no CLAUDE.md or AGENTS.md of its own.

- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`)
- Git: "Before a `git push` to a branch that deploys, say what it carries and ask once." `branch_deploys.py` exits 0 on `main` (`ci.yml` fires) and 1 on `cleo/chat-box`, which is pushed freely. (`/home/tiroir/.claude/CLAUDE.md`)
- Git: "After every push, check CI for that commit" and "Check `.total_count` first: zero checks is not success". (`/home/tiroir/.claude/CLAUDE.md`)
- Tests: "Locally, run only the test files your change touches. Never the full suite, never `pytest -n auto`/xdist, unless `uptime` shows load under 8." The full suite runs in CI on t-compute. (`/home/tiroir/.claude/CLAUDE.md`)
- Tests: "Kill your own test runs when you stop waiting on them". (`/home/tiroir/.claude/CLAUDE.md`)
- Production: "Never write to the gateway VPS (`137.74.12.211`, tiroir.me)." Ticket 06 only reads tiroir-tt. (`/home/tiroir/.claude/CLAUDE.md`)
- Devices and hosts: tiroir-tt runs a hub pinned by the action-list track; a sheaf change reaches it only through that track's stage. Do not change it from here; tell Rocco at the merge of ticket 04, and keep `mount(pane, {doc})` stable or tell him first. (Rocco, this conversation, 2026-11-09)
- Owner's hand: "A blocker goes out through `AskUserQuestion`. Never as prose at the end of a turn." Workers report blockers to you, never to Thierry in their pane. (`/home/tiroir/.claude/CLAUDE.md`)
- Behaviour: the Tell flow stays (SPEC 8 and 9), no Ask control comes back, and the target, waiting and cancel states keep their tests. (Runa, this conversation, 2026-11-09)

## Shared runtime

What a running worker shares beyond its files, one line per repo in Sources, and
how it gets its own copy.

| Repo | Shared when it runs | Own copy per worker |
|---|---|---|
| sheaf | Editable install of `sheafmd`; the hub's port and state; the Playwright browser cache (read only) | `uv run` in the worker's own worktree makes its own `.venv`, proven: a throwaway worktree imports `sheafmd` from its own `src/`. The test fixtures give each test its own `SHEAF_HOME` and port. A worker's own `--basetemp` stays short and distinct (`/tmp/pt-<worker>`) |
| sheaf demo page | One hub on port 27519, for Thierry | none: one at a time, per the handoff; never port 27419, his real hub |

A resource with no own copy goes one at a time: writing code stays parallel, and
you give one worker the turn to run on it, then the next.

## Time windows

None stated on 2026-11-09.

## Language

Report to the owner in French. Files and tickets in French, as the plan is; code, commits and PRs in English, as the repo is.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every code ticket.
- `mattpocock-skills:diagnosing-bugs` — a failing test whose cause is not the new contract.
- `mattpocock-skills:code-review` then `codex-review` — ticket 04, and each PR of tickets 05 and 06.
- `mattpocock-skills:pr` — every PR body.
- `render-doc` — ticket 05 changes its text; any page shown to Thierry.
