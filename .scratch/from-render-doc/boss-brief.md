# Boss brief: sheaf backlog

Written 2026-11-20 by Tarek with `/hand-to-boss`. You are the boss for
track `sheaf-backlog`. Read this file, then every source it names, before you dispatch
anything. This brief points; the sources hold the content.

The owner asked for "all open sheaf tickets". The main graph is the backlog in
`.scratch/from-render-doc/`; four smaller folders of open sheaf work are listed under
**Other open sheaf work** and are yours too, worked by hand from their own frontier.

## Sources

| What | Path |
|---|---|
| Plan (read first, in full): the index of the backlog | `/home/tiroir/Projects/sheaf/.scratch/from-render-doc/README.md` |
| Tickets, one file each | `/home/tiroir/Projects/sheaf/.scratch/from-render-doc/` |
| Spec and glossary the tickets cite | `/home/tiroir/Projects/sheaf/SPEC.md`, `/home/tiroir/Projects/sheaf/GLOSSARY.md` |
| Handoffs | none for this track (the `handoff-*.md` files at the repo root belong to other sessions; leave them) |
| Research | `/home/tiroir/Projects/sheaf/docs/design/` |
| Code | `/home/tiroir/Projects/sheaf` (branch `main`) |
| Code, ticket 168 only | private repo `git@github.com:thinkingtoo/tiroir-mail-replies.git` (its `MOVE_TO` matchers in `tiroir_mail_replies/sheaves.py`). No main checkout exists on the laptop: the worker clones it into its own folder and reads the repo's own rules before touching it |

## Frontier

The frontier on 2026-11-20 11:40 CET, from `frontier.py /home/tiroir/Projects/sheaf/.scratch/from-render-doc`:

```
Ready now: 91, 93, 94, 99, 101, 137, 144, 146, 155, 162, 164, 167, 168, 169, 170, 171
  91  Roots follow-ups: the brand rule, a cancel that is never refused, a forget that waits on a render
  93  MCP door follow-ups: a second file lister, a second status dot, a CLI proof on two connections
  94  The hub can publish a half-written file to open pages
  99  Lifecycle review follow-ups: peer check, restart announcements, stop races, refactors, lint
  101  macOS: a run on main on every Python, and the readings only a real Mac can check
  137  Follow-ups on page edits, version pins and the atomic writers
  144  Enter in a task list: nested and ordered lists, an emptied item with a comment, a loose item
  146  A kept comment draft can go to the wrong paragraph; a leading comment anchor stops a typed task line
  155  Real names and a private host name are back in the public tree, and nothing checks for them
  162  Commit follow-ups: a forgotten root's name, a git flag fixed at registration, a versions store chosen once
  164  The list reads a task line inside a fenced code block in a list item as an action
  167  The door's refusal for a non-member should name the project, not a missing root
  168  Rename the List's "Move to <slug>" to "Belongs to <slug>"
  169  A leader tab that Chrome freezes stops the live updates of every sheaf tab of that browser
  170  A crashed sheaf tab can stay counted as open for up to a minute
  171  Shared live stream: four smaller follow-ups of #474
Waiting on other tickets:
  96  after 101
External blockers:
  139: Thierry chooses (a) or (b) under "Decide first" (not yet asked)
  142: Thierry pastes from a real web mail client and a real online word processor, by hand (not yet asked)
  156: Thierry decides where the per-document "generated" mark lives (not yet asked)
Done: 160
```

Re-run `python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.30.0/skills/hand-to-boss/frontier.py /home/tiroir/Projects/sheaf/.scratch/from-render-doc`
after every ticket that closes; the output above is a snapshot.

External blockers — who holds each one, and what unblocks it:

| Ticket | Waiting on | Who | Asked |
|---|---|---|---|
| 139 | the choice (a) or (b) under "Decide first" | Thierry | not yet |
| 142 | a by-hand paste from a real web mail client and a real online word processor | Thierry | not yet |
| 156 | where the per-document "generated" mark lives | Thierry | not yet |

An external blocker is a person, not a task: nobody on the team works around it.
A blocker the owner holds goes into your tracker's Open blockers and up the
escalation ladder. Ask the three as one `AskUserQuestion` round each, with options
and a recommendation drawn from the ticket text.

Items inside a ready ticket that need a real Mac (101, and 96 after it) or a product
decision (146's second item, 94's "fix in the hub or accept the window") stay unticked
with one line saying why; the rest of the ticket goes ahead.

## Other open sheaf work

Each folder has its own frontier; run `frontier.py` on it the same way. The pulse reads
only the main graph, so you dispatch these yourself.

| Folder | State on 2026-11-20 |
|---|---|
| `/home/tiroir/Projects/sheaf/.scratch/agents-and-waiting-tells/issues/` | Ready: 08 to 14, 16, 17; 15 after 09. 06 and 07 carry claims by Manon (2026-11-07) and Alice (2026-11-08); neither session is in `ListAgents` today. Check their branches and PRs, then release or finish those claims. |
| `/home/tiroir/Projects/sheaf/.scratch/chat-box/issues/` | Nothing ready. 52, 93, 107, 138 and 141 wait on CI evidence or on Codex (back on 2026-11-20 at 14:10). |
| `/home/tiroir/Projects/sheaf/.scratch/work-attach-window/issues/` | Ready: 01. |
| `/home/tiroir/Projects/sheaf/.scratch/follow-ups/` | Loose notes, not graph tickets: two `ready` (abandoned request keeps its worker; `projects.toml` parsed per call), five `open`, one `done`. Two concern agency-tiroir, which is private: work those in the private repo, never here. |

Also owed: a Codex review of the merged PRs #473 (a746a2a) and #474 (a30694be) once
Codex is back. Findings become tickets in this folder, not reverts.

The cross-track boss (tmux session `cross-track`) holds the sheaf release tag and the
Open WebUI phone check (its tickets 11 and 12). Those stay with it; tell it before you
ship a change those depend on.

## Objective

Write it with `boss-goal` from this brief. **Done when**: every ticket not waiting
on an external blocker has Status `done` and its boxes ticked, written as one line
per ticket or per run of them, named `<feature>/<NN>` (`from-render-doc/91 to 99 at Status
done`), so FleetView can show each line's state; the ones still waiting are listed
with who holds them. Give it a `## Tickets` section holding
`/home/tiroir/Projects/sheaf/.scratch/from-render-doc`, one line: the pulse then reads the frontier itself and hands you
every ready ticket each time a worker goes idle.

## Staffing

- You run on `opus`.
- Every worker runs on `sonnet`: `boss-lifecycle.sh spawn <dir> --model sonnet`.
  `BOSS_WORKER_MODEL` is set to the same in your environment, so a spawn without
  `--model` lands there too.
- One git worktree per worker, on its own branch, under `/home/tiroir/Projects/sheaf-wt-<worker>`
  (the repo's existing pattern). Two workers never share a branch or a worktree.
- At most 4 workers at once (no limit but 8 GB of free memory): as many as the
  frontier has ready tickets. When N is a real limit, write it in the goal file as
  `Workers: 4 - the laptop is shared, full suites and browser tests run in CI only` (the pulse ignores a number without a reason).

## Claiming a ticket

The boss claims a ticket at dispatch, before the dispatch message goes out:

```bash
python3 /home/tiroir/.claude/plugins/cache/sweatshop-ai/claude-boss/0.30.0/skills/hand-to-boss/frontier.py claim /home/tiroir/Projects/sheaf/.scratch/from-render-doc <NN> <worker>
git -C /home/tiroir/Projects/sheaf commit -m "Claim <NN> for <worker>" -- <ticket file>
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
source wins where this summary is short.

- Public repo: "`sweatshop-ai/sheaf` is a PUBLIC repo … never put client names, hosts, IPs, people or client-box security facts there; write them in tiroir-clients or thinkingtoo (private)." (`/home/tiroir/.claude/projects/-home-tiroir-Projects-sheaf/memory/tiroir-layer-is-private.md`). Commits use the noreply identity already set in the checkout ("Git identity for anything PUBLIC: `tiroir <202564+tiroir@users.noreply.github.com>`", `/home/tiroir/.claude/CLAUDE.md`).
- Shared tree: "Another session may share this checkout. Before a commit, `git status` and stage only your own paths by name; for more than a small edit, use a worktree." (`/home/tiroir/.claude/CLAUDE.md`). "Never `git checkout` in a shared working directory when other workers are in the same project." (same file)
- Tests: "Locally, run only the test files your change touches. Never the full suite, never `pytest -n auto`/xdist, unless `uptime` shows load under 8." "Browser tests (Playwright, headless Chrome e2e) never run on the laptop, not even one file: run them on t-compute over ssh or in CI." (`/home/tiroir/.claude/CLAUDE.md`)
- Reviews: "One review round per PR … A PR gets Matt's `code-review` plus `/codex-review` once." "NO-GO only for a serious defect … minor findings are fixed in the same push, with no new round." (`/home/tiroir/.claude/CLAUDE.md`)
- Git: nothing deploys from `main`: `branch_deploys.py /home/tiroir/Projects/sheaf main` lists only `ci.yml` (tests), so merge to `main` yourself, no question (`/home/tiroir/.claude/CLAUDE.md`, "A branch whose workflows only run tests … is not a deploy"). "After every push, check CI for that commit … A push is not finished until its checks are green." (same file)
- Devices: the live hub on port 27419 is Thierry's, installed with `uv tool` and restarted only by the merge desk's Install or by Thierry. No worker installs, stops or restarts it (`sheaf stop`, `sheaf restart`, `uv tool install sheafmd`); a fix reaches him through the desk.

## Shared runtime

What a running worker shares beyond its files, one line per repo in Sources, and
how it gets its own copy.

| Repo | Shared when it runs | Own copy per worker |
|---|---|---|
| sheaf | Thierry's installed hub (`~/.local/share/uv/tools/sheafmd`, port 27419, state in `~/.local/state/sheaf`) | `uv run` in the worker's own worktree builds a `.venv` there that imports that worktree's `src/sheafmd` (proved 2026-11-20 in a detached worktree). Tests set their own `SHEAF_HOME` and `SHEAF_PORT` (`tests/conftest.py:191`, `:228`) and refuse port 27419. A hand-run hub sets `SHEAF_HOME` to a scratch folder and `SHEAF_PORT` to a free port, and is stopped by the worker that started it. |
| tiroir-mail-replies | nothing shared | its own clone |

## Time windows

None stated on 2026-11-20.

## Language

Report to the owner in Dutch. Files, commits, tickets and PRs in English.

## Suggested skills

- `/claude-boss:boss` — you are running it.
- `mattpocock-skills:tdd` — every code ticket.
- `mattpocock-skills:diagnosing-bugs` — 94, 146, 164, 169, 170 and the flaky-test notes in `follow-ups/`.
- `mattpocock-skills:code-review`, then `/codex-review` — once per PR before the merge.
- `supply-chain-risk-auditor` — if a ticket adds or bumps a dependency.
